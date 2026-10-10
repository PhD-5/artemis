"""Business-level Yuri catalog validation and RPC result semantics."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from artemis.clients.yuri_rpc_client import YuriRpcError
from artemis.tools.yuri import YURI_TOOLS, execute_yuri


@pytest.fixture
def client():
    stub = MagicMock()
    stub.call = AsyncMock()
    stub.run_job = AsyncMock()
    stub.poll_job = AsyncMock()
    stub.pull_screenshot = AsyncMock(return_value="/host/artifacts/screenshot.png")
    stub.ensure_farm_rom = AsyncMock()
    return stub


async def execute(client, name, **args):
    return await execute_yuri(client, YURI_TOOLS[name], args)


def assert_no_rpc(client):
    client.call.assert_not_awaited()
    client.run_job.assert_not_awaited()
    client.poll_job.assert_not_awaited()
    client.pull_screenshot.assert_not_awaited()
    client.ensure_farm_rom.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("yuri_app_launch", {"package": "com.example.app;id"}),
        ("yuri_app_install", {"apk": "/tmp/x.apk;id"}),
        ("yuri_device_get_settings", {"ns": "system;id", "key": "brightness"}),
        ("yuri_device_put_settings", {"ns": "secure", "key": "foo", "value": "$(id)"}),
        ("yuri_ui_input", {"text": "hello' ; id"}),
        (
            "yuri_device_modify",
            {"package": "com.example.app", "seed": 1 << 63, "brand": "Pixel_6", "country": "jp"},
        ),
        (
            "yuri_device_modify",
            {"package": "com.example.app", "seed": 1, "brand": "../../x", "country": "jp"},
        ),
        ("yuri_device_modify_profile", {"package": "com.example.app", "device_info": "bad=!"}),
        ("yuri_network_start_clash", {"clash": "%%%"}),
        ("yuri_app_data_backup", {"package": "com.example.app", "path": "/data/../tmp"}),
        (
            "yuri_app_data_backup",
            {"package": "com.example.app", "path": "/data/backup", "exclude": "*/a;id"},
        ),
        ("yuri_app_is_installed", {"package": "com.example.app", "extra": 1}),
        ("yuri_job_poll", {"id": "j-1"}),
    ],
)
async def test_bad_args_prevent_any_rpc(client, name, args):
    result = await execute(client, name, **args)
    assert result["ok"] is False
    assert result["code"] == "INVALID_ARGS"
    assert_no_rpc(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [False, None, ""])
async def test_query_false_null_or_empty_is_success(client, answer):
    name = "yuri_app_is_installed" if answer is False else "yuri_device_get_settings"
    client.call.return_value = answer
    args = {"package": "com.example.app"} if answer is False else {"ns": "secure", "key": "flag"}
    result = await execute(client, name, **args)
    assert result["ok"] is True
    assert result["data"] == answer
    assert json.dumps(answer) in result["message"]


@pytest.mark.asyncio
async def test_ui_false_is_action_failure(client):
    client.call.return_value = False
    result = await execute(client, "yuri_click_text", text="Launch")
    assert result["ok"] is False
    assert result["code"] == "ACTION_FAILED"
    client.call.assert_awaited_once_with(
        "recognition.screenClickText", {"text": "Launch", "strict": False}
    )


@pytest.mark.asyncio
async def test_shell_exit_status_not_just_rpc_success(client):
    client.call.return_value = {"status": 13, "stdout": "", "stderr": "permission denied"}
    result = await execute(client, "yuri_shell_exec", cmd="id")
    assert result["code"] == "SHELL_FAILED"
    assert result["data"]["status"] == 13
    assert "permission denied" in result["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"job_id": "opaque", "state": "done", "result": False},
        {"job_id": "opaque", "state": "failed", "error": "no space"},
    ],
)
async def test_job_false_or_failed_is_failure(client, response):
    client.run_job.return_value = response
    result = await execute(client, "yuri_app_install", apk="/data/local/tmp/app.apk")
    assert result["ok"] is False
    assert result["code"] == "JOB_FAILED"
    assert result["data"] == response
    client.run_job.assert_awaited_once_with("app.install", {"apk": "/data/local/tmp/app.apk"})


@pytest.mark.asyncio
async def test_pending_job_never_claims_success(client):
    client.poll_job.return_value = {"job_id": "opaque", "state": "running"}
    result = await execute(client, "yuri_job_poll", job_id="opaque")
    assert result["ok"] is False
    assert result["code"] == "JOB_PENDING"
    client.poll_job.assert_awaited_once_with("opaque")
    client.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_sub_get_text_translates_local_center_and_rect_but_not_remote_response(client):
    remote = [{"text": "send", "x": 12.5, "y": 9, "rect": [[1, 2], [10, 2], [10, 12], [1, 12]]}]
    client.call.return_value = remote
    result = await execute(client, "yuri_sub_get_text", x=100, y=200, w=300, h=400)
    assert result["ok"] is True
    assert result["data"] == [
        {
            "text": "send",
            "x": 112.5,
            "y": 209,
            "rect": [[101, 202], [110, 202], [110, 212], [101, 212]],
        }
    ]
    assert remote[0]["x"] == 12.5
    assert remote[0]["rect"][0] == [1, 2]


@pytest.mark.asyncio
async def test_sub_find_text_point_is_already_absolute(client):
    client.call.return_value = {"x": 117, "y": 236}
    result = await execute(client, "yuri_sub_find_text", text="send", x=100, y=200, w=300, h=400)
    assert result["data"] == {"x": 117, "y": 236}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        {"app_uid": 10001},
        {
            "app_pkg": "com.example.app",
            "remote_host": "proxy.test",
            "remote_port": "9999",
            "local_port": "0",
        },
        {
            "app_uid": 10001,
            "app_pkg": "com.example.app",
            "remote_host": "proxy.test",
            "remote_port": "9999",
        },
        {"app_uid": 10001, "remote_host": "proxy.test", "remote_port": "65536"},
        {"app_uid": 10001, "remote_host": "host;id", "remote_port": "1000"},
        {"app_uid": 10001, "https_capture": True, "remote_host": "proxy.test"},
    ],
)
async def test_proxy_requires_valid_conditional_arguments(client, args):
    result = await execute(client, "yuri_network_start_proxy", **args)
    assert result["code"] == "INVALID_ARGS"
    assert_no_rpc(client)


@pytest.mark.asyncio
async def test_rpc_errors_have_code_and_structured_data(client):
    client.call.side_effect = YuriRpcError("BAD_ARGS", "Yuri rejected request", {"field": "key"})
    result = await execute(client, "yuri_device_get_settings", ns="system", key="my_key")
    assert result["ok"] is False
    assert result["code"] == "BAD_ARGS"
    assert result["data"] == {"field": "key"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("yuri_device_reset", {}),
        (
            "yuri_device_modify",
            {"package": "com.example.app", "seed": 1, "brand": "Pixel_6", "country": "jp"},
        ),
        ("yuri_device_modify_profile", {"package": "com.example.app", "device_info": "Zm9v"}),
    ],
)
async def test_farm_precondition_blocks_mutation(client, name, args):
    client.ensure_farm_rom.side_effect = YuriRpcError("UNSUPPORTED", "Not a Yuri farm ROM")
    result = await execute(client, name, **args)
    assert result["ok"] is False
    assert result["code"] == "UNSUPPORTED"
    client.ensure_farm_rom.assert_awaited_once()
    client.call.assert_not_awaited()
    client.run_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_ordinary_query_does_not_probe_farm_rom(client):
    client.call.return_value = "value"
    assert (await execute(client, "yuri_device_get_settings", ns="system", key="flag"))["ok"]
    client.ensure_farm_rom.assert_not_awaited()
