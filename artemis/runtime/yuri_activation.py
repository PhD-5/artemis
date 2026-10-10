"""Cheap task gate; the Yuri plugin is imported only after explicit user opt-in."""

import re
from typing import Any


_NAME = r"(?<![a-zA-Z0-9_])yuri(?![a-zA-Z0-9_])"
_QUOTED = re.compile(
    r"```[\s\S]*?```|`[^`]*`|\"[^\"\n]*\"|(?<!\w)'[^'\n]*'|“[^”\n]*”|‘[^’\n]*’|(?m:^\s*>.*$)"
)
_NEGATIVE = re.compile(
    rf"(?:不要|禁止|禁用|不用|不使用|不调用|不启用|不允许|不准|请勿|别|避免|无需|无须|不需要)[^。！？;；\n]*{_NAME}"
    rf"|(?:do\s+not|don't|must\s+not|mustn't|should\s+not|shouldn't|never|without|disable|avoid|no)\b[^.!?;\n]*{_NAME}"
    rf"|{_NAME}[^。！？;；\n]{{0,8}}(?:禁用|关闭|不可用|disabled|off)"
    rf"|{_NAME}\s+(?:must|should|is)\s+not\s+(?:be\s+)?(?:used|enabled|invoked)\b",
    re.IGNORECASE,
)
_POSITIVE = re.compile(
    rf"(?:使用|调用|通过|启用|借助|利用|开启|采用|用)[^。！？;；\n]{{0,10}}{_NAME}"
    rf"|(?:在|对|针对)\s*{_NAME}\s*(?:设备|手机)"
    rf"|\b(?:use|using|invoke|enable|via|with)\s+(?:the\s+)?{_NAME}"
    rf"|{_NAME}\s*(?:的\s*)?(?:OCR|改机|代理|能力|功能|RPC)"
    rf"|{_NAME}\s+(?:device|phone)\b",
    re.IGNORECASE,
)
_DISCUSSION = re.compile(
    r"^(?:请\s*|please\s+)?(?:解释|说明|介绍|讨论|展示示例|如何|示例|例如|文档|参考示例|explain\b|describe\b|how\b|example\b|documentation\b|the\s+(?:readme|docs)\b)",
    re.IGNORECASE,
)
_POLITE = re.compile(
    r"^(?:(?:请你|请|我想请你|我希望你|我希望|我想|我需要|希望你|希望|想要|需要|先|再|然后|并|现在|帮我|务必|必须|仅|只|优先)\s*|(?:i\s+(?:want|need|would\s+like)\s+to|(?:can|could)\s+you(?:\s+please)?|please|now|then|also)\s+)+",
    re.IGNORECASE,
)
_ACTION_START = re.compile(
    r"^(?:读取|获取|识别|查找|点击|修改|设置|改机|安装|卸载|备份|恢复|启动|停止|把|将|read\b|get\b|find\b|click\b|modify\b|set\b|install\b|uninstall\b|back\s+up\b|restore\b|start\b|stop\b)",
    re.IGNORECASE,
)


def requests_yuri(goal: str) -> bool:
    """Only a positive, unquoted instruction in the original user goal opts in.

    Any explicit prohibition wins. Incidental mentions, examples and code do not
    grant device capabilities. Runtime pages/tool results are never inputs here.
    """
    if not isinstance(goal, str) or "yuri" not in goal.casefold():
        return False
    text = _QUOTED.sub("", goal)
    if _NEGATIVE.search(text):
        return False
    for clause in re.split(r"[。！？.!?;；，,\n]", text):
        clause = re.sub(r"^[\s\d.)、*-]+", "", clause).strip()
        if _DISCUSSION.search(clause):
            continue
        clause = _POLITE.sub("", clause)
        if _POSITIVE.search(clause) and (_POSITIVE.match(clause) or _ACTION_START.match(clause)):
            return True
    return False


def active_yuri(ctx: Any) -> Any | None:
    """Return only an installed, live plugin; missing contexts remain ordinary."""
    plugin = getattr(ctx, "yuri_plugin", None)
    return plugin if plugin is not None and getattr(plugin, "active", False) is True else None


async def prepare_task_yuri(ctx: Any, goal: str, profile: str | None = None) -> None:
    """Activate after the device lock, before any runner sees its tools.
    Ordinary tasks neither import the plugin nor run a probe. Failure is explicit
    and leaves both the context plugin and actuator untouched.
    """
    if not requests_yuri(goal):
        return
    from artemis.config.yuri import YuriConfig

    config = getattr(getattr(ctx, "agent_config", None), "yuri", None)
    if config is None:
        config = YuriConfig()
    if not config.enabled:
        raise RuntimeError(
            "Yuri was requested, but the optional plugin is disabled (agent.yuri.enabled)."
        )
    from artemis.tools.yuri_plugin import YuriPlugin

    plugin = YuriPlugin(ctx, config, profile)
    try:
        await plugin.client.probe()
        plugin.install()
    except BaseException:
        await plugin.client.aclose()
        raise
