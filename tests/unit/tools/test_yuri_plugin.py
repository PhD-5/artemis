"""Exercise plugin authorization and business outcomes over the real MCP adapter."""

import json
import shlex
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from artemis.agents.flash.runner import FlashRunner, _TurnRecord
from artemis.agents.operator.operator import OperatorNode
from artemis.agents.validator.action_execution import exec_action
from artemis.agents.validator.execution_loop import _process_action
from artemis.agents.validator.validator import ValidatorNode
from artemis.clients.yuri_rpc_client import YuriRpcClient, YuriRpcError
from artemis.config.yuri import YuriConfig
from artemis.graph.state import State
from artemis.mcp.action_executor import McpActionExecutor
from artemis.mcp.action_session import get_action_session
from artemis.mcp.actuators.mock import MockActuator
from artemis.runtime.yuri_activation import prepare_task_yuri


class RpcDevice:
    def __init__(self, *, installed=True, alive=True):
        self.installed = installed
        self.alive = alive
        self.requests = []
        self.clicks = 0
        self.answers = {
            "recognition.screenFindText": None,
            "shell.exec": {"status": 13, "stdout": "", "stderr": "denied"},
        }

    async def execute(self, *args, **kwargs):
        command = args[1]
        self.requests.append(command)
        if command == "pm path com.bricrt.yuri.client":
            return 0, "package:/data/app/yuri/base.apk" if self.installed else "", ""
        if not self.alive:
            return 2, "", "Connection refused"
        tokens = shlex.split(command)
        method, params = tokens[-2], json.loads(tokens[-1])
        if method == "ping":
            data = {"pong": True, "version": "1.8.6"}
        elif method == "app.isInstalled":
            data = params["package"] == "com.example.installed"
        elif method == "recognition.screenClickText":
            self.clicks += 1
            data = False
        else:
            data = self.answers[method]
        return 0, json.dumps({"id": 1, "ok": True, "data": data}), ""


def context(*, allowed=None, deny=None):
    backend = MockActuator(width=1000, height=2000)
    ctx = backend.ctx
    ctx.actuator = backend
    ctx.adb_client = SimpleNamespace(host="127.0.0.1", port=5037)
    ctx.agent_config = SimpleNamespace(
        yuri=YuriConfig(enabled=True, allowed_tools=allowed),
        denylisted_tools=deny or {},
    )
    return ctx


def bind_device(monkeypatch, device):
    async def transport(client, *args, **kwargs):
        return await device.execute(*args, **kwargs)

    monkeypatch.setattr(YuriRpcClient, "_exec", transport)


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["flash", "pro"])
async def test_ordinary_task_preserves_actuator_and_does_not_probe(monkeypatch, profile):
    device = RpcDevice()
    bind_device(monkeypatch, device)
    ctx = context()
    original = ctx.actuator
    async with ctx:
        await prepare_task_yuri(ctx, "检查应用是否已安装", profile)
        assert ctx.actuator is original and ctx.yuri_plugin is None
        assert device.requests == []
        executor = McpActionExecutor(ctx, agent_name="flash")
        result = await executor.execute("yuri_ping", {}, "call", State.initial("普通任务"))
        assert result.status == "error" and device.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("installed,alive", [(False, True), (True, False)])
async def test_probe_failure_does_not_install_tools_or_change_backend(
    monkeypatch, installed, alive
):
    device = RpcDevice(installed=installed, alive=alive)
    bind_device(monkeypatch, device)
    ctx = context()
    original = ctx.actuator
    with pytest.raises(YuriRpcError):
        await prepare_task_yuri(ctx, "使用 Yuri 检查应用", "flash")
    assert ctx.yuri_plugin is None and ctx.actuator is original
    assert all(
        "am start" not in command and "su" not in shlex.split(command)
        for command in device.requests
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["flash", "pro"])
async def test_query_false_and_no_match_are_successful_answers_not_actions(monkeypatch, profile):
    device = RpcDevice()
    bind_device(monkeypatch, device)
    ctx = context(allowed=["yuri_app_is_installed", "yuri_find_text"])
    original = ctx.actuator
    async with ctx:
        await prepare_task_yuri(ctx, "使用 Yuri 查询应用和文字", profile)
        if profile == "flash":
            runner = FlashRunner(ctx, goal="使用 Yuri 查询")
            state = State.initial("使用 Yuri 查询")
            result = await runner.executor.execute(
                "yuri_app_is_installed",
                {"package": "com.example.missing"},
                "query",
                state,
            )
            assert result.status == "success" and result.metadata["data"] is False
            assert "yuri_app_is_installed" not in runner.executor.action_tool_names
            missed = await runner.executor.execute(
                "yuri_find_text", {"text": "missing"}, "find", state
            )
            assert missed.status == "success" and missed.metadata["data"] is None
        else:
            tools = {tool.name: tool for tool in ctx.yuri_plugin.langchain_tools()}
            answer = await tools["yuri_app_is_installed"].ainvoke(
                {"package": "com.example.missing"}
            )
            assert "false" in answer
            missed = await tools["yuri_find_text"].ainvoke({"text": "missing"})
            assert "null" in missed
            assert "yuri_app_is_installed" not in OperatorNode(ctx)._available_device_actions()
        assert original.action_history == []
    assert ctx.yuri_plugin is None and ctx.actuator is original


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["flash", "pro"])
async def test_failed_ocr_click_is_not_success_and_never_retried(monkeypatch, profile):
    device = RpcDevice()
    bind_device(monkeypatch, device)
    ctx = context(allowed=["yuri_click_text"])
    async with ctx:
        await prepare_task_yuri(ctx, "使用 Yuri 点击不存在的文字", profile)
        state = State.initial("使用 Yuri 点击")
        if profile == "flash":
            executor = McpActionExecutor(ctx, agent_name="flash")
            result = await executor.execute("yuri_click_text", {"text": "missing"}, "click", state)
            assert result.status == "error"
        else:
            node = ValidatorNode(ctx)
            session = await get_action_session(ctx)
            outcome = await _process_action(
                node,
                state,
                session,
                {"action": "yuri_click_text", "args": {"text": "missing"}},
                "yuri_click_text",
                "",
                burst=False,
            )
            assert not outcome.success
            assert outcome.action_item["yuri_result"]["yuri_code"] == "ACTION_FAILED"
        assert device.clicks == 1


@pytest.mark.asyncio
async def test_pro_translation_and_validator_preserve_shell_failure_data(monkeypatch):
    device = RpcDevice()
    bind_device(monkeypatch, device)
    ctx = context(allowed=["yuri_shell_exec"])
    async with ctx:
        await prepare_task_yuri(ctx, "使用 Yuri 执行明确的 root 命令", "pro")
        node = OperatorNode(ctx)
        actions, error = node._translate_and_validate_tool(
            {"name": "yuri_shell_exec", "args": {"cmd": "id"}},
            State.initial("Yuri"),
        )
        assert error is None
        session = await get_action_session(ctx)
        success, reason = await exec_action(ctx, session, actions[0])
        assert not success and "denied" in reason
        assert actions[0]["yuri_result"]["data"]["status"] == 13


@pytest.mark.asyncio
async def test_config_and_role_permissions_reject_direct_calls(monkeypatch):
    device = RpcDevice()
    bind_device(monkeypatch, device)
    ctx = context(allowed=["yuri_ping", "yuri_shell_exec"], deny={"flash": ["yuri_shell_exec"]})
    async with ctx:
        await prepare_task_yuri(ctx, "使用 Yuri 查询", "flash")
        runner = FlashRunner(ctx, goal="使用 Yuri 查询")
        assert "yuri_shell_exec" not in {tool.name for tool in runner._get_tools()}
        before = list(device.requests)
        rejected = await runner.executor.execute(
            "yuri_shell_exec", {"cmd": "id"}, "denied", State.initial("Yuri")
        )
        assert rejected.status == "error" and device.requests == before
        session = await get_action_session(ctx)
        direct = await session.call_raw("yuri_shell_exec", {"cmd": "id"})
        assert direct.structuredContent["ok"] is False and device.requests == before
        unregistered = await runner.executor.execute(
            "yuri_device_reset", {}, "denied", State.initial("Yuri")
        )
        assert unregistered.status == "error" and device.requests == before


@pytest.mark.asyncio
async def test_flash_mutation_burst_is_rejected_before_any_operation(monkeypatch):
    device = RpcDevice()
    bind_device(monkeypatch, device)
    ctx = context(allowed=["yuri_click_text"])
    async with ctx:
        await prepare_task_yuri(ctx, "使用 Yuri 点击文字", "flash")
        runner = FlashRunner(ctx, goal="使用 Yuri 点击文字")
        runner._llm = None
        messages = []
        before = list(device.requests)
        await runner._process_tool_calls(
            [
                {"name": "yuri_click_text", "args": {"text": "first"}, "id": "a"},
                {"name": "press_key", "args": {"key": "home"}, "id": "b"},
            ],
            State.initial("Yuri"),
            messages,
            "",
            {},
            b"",
            "",
            0,
            _TurnRecord(),
        )
        assert device.requests == before and ctx.actuator.backend.action_history == []
        assert [msg.status for msg in messages if isinstance(msg, ToolMessage)] == [
            "error",
            "error",
        ]
