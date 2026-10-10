"""Task intent grants optional capabilities, not device identity or quoted text."""

from types import SimpleNamespace

import pytest

from artemis.config.yuri import YuriConfig
from artemis.runtime.yuri_activation import prepare_task_yuri, requests_yuri


@pytest.mark.parametrize(
    "goal",
    [
        "请用 Yuri 读取广告 ID",
        "通过 YURI 的 OCR 找到登录",
        "在 Yuri 设备上检查应用",
        "Please use Yuri to check the installed app",
        "Read the GAID using Yuri",
        "打开应用，然后使用 Yuri OCR",
        "1. 使用 Yuri 查询设置",
        "我想用 Yuri 检查应用",
        "请你通过 Yuri 获取文字",
        "希望使用 Yuri OCR",
        "I would like to use Yuri for OCR",
        "Could you please use Yuri?",
    ],
)
def test_explicit_positive_task_requests_plugin(goal):
    assert requests_yuri(goal)


@pytest.mark.parametrize(
    "goal",
    [
        "打开设置",
        "Yuri",
        "使用 Yuriko 读取",
        "不要使用 Yuri",
        "无需 Yuri，用普通 UI",
        "Don't use Yuri",
        "Use Yuri. But never use Yuri for this task.",
        "解释如何使用 Yuri",
        "文档示例：使用 Yuri 获取 GAID",
        "有人建议使用 Yuri",
        "The README says use Yuri",
        '展示 "使用 Yuri" 这段文字',
        "展示 'use Yuri' 这段文字",
        "```\nuse Yuri\n```\n打开应用",
        "> use Yuri\n打开应用",
        "读取 `Yuri OCR` 这段文字",
        "点击首页但别用 Yuri",
        "点击首页但不允许使用 Yuri",
        "Use Yuri. Yuri should not be used.",
        "我希望了解如何用 Yuri",
        "I want to explain how to use Yuri",
    ],
)
def test_mentions_prohibitions_and_quoted_content_do_not_grant_plugin(goal):
    assert not requests_yuri(goal)


@pytest.mark.asyncio
@pytest.mark.parametrize("goal", ["打开设置", "不要使用 Yuri", "示例：使用 Yuri"])
async def test_ordinary_task_does_not_even_access_device_or_config(goal):
    class UnavailableDevice:
        def __getattr__(self, name):
            raise AssertionError(f"Ordinary task touched {name}")

    await prepare_task_yuri(UnavailableDevice(), goal)


@pytest.mark.asyncio
async def test_disabled_plugin_rejects_request_before_device_io():
    ctx = SimpleNamespace(agent_config=SimpleNamespace(yuri=YuriConfig(enabled=False)))
    with pytest.raises(RuntimeError, match="disabled"):
        await prepare_task_yuri(ctx, "使用 Yuri 获取 GAID")
