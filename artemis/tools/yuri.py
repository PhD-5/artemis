"""Opt-in Yuri RPC tool definitions and structured result handling.

Schemas are shared by all tool surfaces. They deliberately validate values that
Yuri later interpolates into unquoted Android shell commands; JSON escaping alone
cannot protect those commands.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from artemis.clients.yuri_rpc_client import YuriRpcClient, YuriRpcError


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NoArgs(Args):
    pass


Package = str
_SAFE_PACKAGE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
_SAFE_PATH = re.compile(r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
_SAFE_ATOM = re.compile(r"[A-Za-z0-9_.-]+")
_SAFE_SETTING_VALUE = re.compile(r"[-A-Za-z0-9_./:+@=,]+")
_SAFE_EXCLUDE = re.compile(r"(?:\*/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
_SAFE_HOST = re.compile(r"[A-Za-z0-9.:-]+")


def _safe(value: str, pattern: re.Pattern[str], name: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"{name} contains unsafe characters or has an invalid format")
    return value


def _path(value: str) -> str:
    _safe(value, _SAFE_PATH, "path")
    if any(part in (".", "..") for part in value.split("/")):
        raise ValueError("path must not contain . or .. segments")
    return value


def _port(value: str, name: str) -> str:
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise ValueError(f"{name} must be a port from 1 to 65535")
    return value


class PackageArgs(Args):
    package: Package

    @field_validator("package")
    @classmethod
    def safe_package(cls, value: str) -> str:
        return _safe(value, _SAFE_PACKAGE, "package")


class SettingsArgs(Args):
    ns: Literal["system", "secure", "global"]
    key: str

    @field_validator("key")
    @classmethod
    def safe_key(cls, value: str) -> str:
        return _safe(value, _SAFE_ATOM, "key")


class PutSettingsArgs(SettingsArgs):
    value: str

    @field_validator("value")
    @classmethod
    def safe_value(cls, value: str) -> str:
        return _safe(value, _SAFE_SETTING_VALUE, "value")


class TextArgs(Args):
    text: str = Field(min_length=1)
    strict: bool = False


class RegionArgs(Args):
    x: int = Field(ge=0, le=2147483647)
    y: int = Field(ge=0, le=2147483647)
    w: int = Field(gt=0, le=2147483647)
    h: int = Field(gt=0, le=2147483647)

    @model_validator(mode="after")
    def fits_java_int(self) -> RegionArgs:
        if self.x + self.w > 2147483647 or self.y + self.h > 2147483647:
            raise ValueError("region extends beyond Java int coordinates")
        return self


class SubTextArgs(TextArgs, RegionArgs):
    pass


class ClickArgs(Args):
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)


class SwipeArgs(Args):
    fromX: float = Field(ge=0, allow_inf_nan=False)
    fromY: float = Field(ge=0, allow_inf_nan=False)
    toX: float = Field(ge=0, allow_inf_nan=False)
    toY: float = Field(ge=0, allow_inf_nan=False)
    duration: int = Field(default=100, gt=0, le=2147483647)


class InputArgs(Args):
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def safe_keyboard_text(cls, value: str) -> str:
        # UIControl surrounds text with single quotes in a root shell command.
        if "'" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("text cannot contain a quote or control character")
        return value


class ModifyArgs(PackageArgs):
    seed: int = Field(ge=-(1 << 63), le=(1 << 63) - 1)
    brand: str
    country: str

    @field_validator("brand", "country")
    @classmethod
    def safe_template(cls, value: str) -> str:
        return _safe(value, _SAFE_ATOM, "brand/country")


class ModifyProfileArgs(PackageArgs):
    device_info: str

    @field_validator("device_info")
    @classmethod
    def valid_base64(cls, value: str) -> str:
        _validate_base64(value)
        return value


class InstallArgs(Args):
    apk: str

    @field_validator("apk")
    @classmethod
    def safe_apk(cls, value: str) -> str:
        if value.startswith(("http://", "https://")):
            url = urlsplit(value)
            if not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError(
                    "apk URL requires a host and a safe filename, without credentials, query or fragment"
                )
            _safe(value.rsplit("/", 1)[-1], _SAFE_ATOM, "download filename")
        else:
            _path(value)
        if not value.lower().endswith((".apk", ".xapk")):
            raise ValueError(
                "apk must be an absolute device path or HTTP(S) URL ending in .apk or .xapk"
            )
        return value


class BackupArgs(PackageArgs):
    path: str
    exclude: str | None = None

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return _path(value)

    @field_validator("exclude")
    @classmethod
    def safe_exclude(cls, value: str | None) -> str | None:
        if value is not None and value:
            for item in value.split(","):
                _safe(item, _SAFE_EXCLUDE, "exclude")
                if any(part in (".", "..") for part in item.split("/")):
                    raise ValueError("exclude must not contain . or .. segments")
        return value


class RestoreArgs(Args):
    package: Package
    path: str

    @field_validator("package")
    @classmethod
    def safe_package(cls, value: str) -> str:
        return _safe(value, _SAFE_PACKAGE, "package")

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return _path(value)


class ShellArgs(Args):
    cmd: str = Field(min_length=1)


class ProxyArgs(Args):
    app_uid: int | None = Field(default=None, ge=0, le=2147483647)
    app_pkg: str | None = None
    https_capture: bool = False
    local_port: str = "16666"
    remote_host: str | None = None
    remote_port: str | None = None
    mitm_port: int = Field(default=18888, ge=1, le=65535)
    relay_type: Literal["socks5", "http-connect"] = "socks5"

    @field_validator("app_pkg")
    @classmethod
    def safe_package(cls, value: str | None) -> str | None:
        return _safe(value, _SAFE_PACKAGE, "app_pkg") if value is not None else None

    @field_validator("local_port", "remote_port")
    @classmethod
    def safe_port(cls, value: str | None, info: Any) -> str | None:
        return _port(value, info.field_name) if value is not None else None

    @field_validator("remote_host")
    @classmethod
    def safe_host(cls, value: str | None) -> str | None:
        return _safe(value, _SAFE_HOST, "remote_host") if value is not None else None

    @model_validator(mode="after")
    def validate_proxy(self) -> ProxyArgs:
        if (self.app_uid is None) == (self.app_pkg is None):
            raise ValueError("provide exactly one of app_uid or app_pkg")
        if self.https_capture:
            if self.remote_host is not None or self.remote_port is not None:
                raise ValueError("remote_host/remote_port are not used with https_capture")
            if self.relay_type != "socks5":
                raise ValueError("relay_type is not used with https_capture")
        elif self.remote_host is None or self.remote_port is None:
            raise ValueError("remote_host and remote_port are required unless https_capture")
        elif self.mitm_port != 18888:
            raise ValueError("mitm_port is only used with https_capture")
        return self


class ClashArgs(Args):
    clash: str

    @field_validator("clash")
    @classmethod
    def valid_base64(cls, value: str) -> str:
        _validate_base64(value)
        return value


def _validate_base64(value: str) -> None:
    try:
        decoded = base64.b64decode(value, validate=True)
        if not decoded:
            raise ValueError("base64 payload must not be empty")
        decoded.decode("utf-8")
    except (binascii.Error, UnicodeError) as exc:
        raise ValueError("payload must be base64-encoded UTF-8") from exc


class PollArgs(Args):
    job_id: str = Field(min_length=1)


@dataclass(frozen=True)
class YuriToolSpec:
    name: str
    method: str
    args_schema: type[Args]
    description: str
    kind: Literal["query", "ui", "system"]
    result_kind: Literal["value", "bool", "shell", "job", "screenshot"]


def _spec(
    name: str,
    method: str,
    schema: type[Args],
    description: str,
    kind: Literal["query", "ui", "system"],
    result: Literal["value", "bool", "shell", "job", "screenshot"],
) -> YuriToolSpec:
    usage = " Use only when the user's task explicitly requests Yuri." + (
        " This is a query; read DATA before choosing an action."
        if kind == "query"
        else " Run alone; do not retry an uncertain result."
    )
    return YuriToolSpec("yuri_" + name, method, schema, description + usage, kind, result)


_SPECS = (
    _spec("ping", "ping", NoArgs, "Read Yuri RPC version and pong.", "query", "value"),
    _spec(
        "device_get_gaid",
        "device.getGAID",
        NoArgs,
        "Read Google Advertising ID (empty if unavailable).",
        "query",
        "value",
    ),
    _spec(
        "device_get_settings",
        "device.getSettings",
        SettingsArgs,
        "Read Android setting.",
        "query",
        "value",
    ),
    _spec(
        "device_put_settings",
        "device.putSettings",
        PutSettingsArgs,
        "Write Android setting.",
        "system",
        "bool",
    ),
    _spec(
        "device_reset",
        "device.reset",
        NoArgs,
        "Clear active device-property override.",
        "system",
        "bool",
    ),
    _spec(
        "device_screenshot",
        "device.screenShot",
        NoArgs,
        "Capture screenshot and pull it to a host artifact.",
        "query",
        "screenshot",
    ),
    _spec(
        "device_modify",
        "device.modify",
        ModifyArgs,
        "Modify device profile for installed target package (farm only).",
        "system",
        "job",
    ),
    _spec(
        "device_modify_profile",
        "device.modifyProfile",
        ModifyProfileArgs,
        "Apply base64 UTF-8 profile for target package (farm only).",
        "system",
        "job",
    ),
    _spec(
        "find_text",
        "recognition.screenFindText",
        TextArgs,
        "Find OCR text; absolute screen point or null.",
        "query",
        "value",
    ),
    _spec(
        "sub_find_text",
        "recognition.subScreenFindText",
        SubTextArgs,
        "Find OCR text in region; point already absolute or null.",
        "query",
        "value",
    ),
    _spec(
        "click_text",
        "recognition.screenClickText",
        TextArgs,
        "Find and click OCR text.",
        "ui",
        "bool",
    ),
    _spec(
        "sub_click_text",
        "recognition.subScreenClickText",
        SubTextArgs,
        "Find and click OCR text in region.",
        "ui",
        "bool",
    ),
    _spec(
        "get_text",
        "recognition.screenGetText",
        NoArgs,
        "Read OCR words with absolute points and quadrilaterals.",
        "query",
        "value",
    ),
    _spec(
        "sub_get_text",
        "recognition.subScreenGetText",
        RegionArgs,
        "Read OCR words from region; translate points and rect to screen pixels.",
        "query",
        "value",
    ),
    _spec(
        "ui_click", "ui.screenClick", ClickArgs, "Tap absolute screen coordinates.", "ui", "bool"
    ),
    _spec(
        "ui_swipe",
        "ui.screenSwipe",
        SwipeArgs,
        "Swipe between absolute screen coordinates.",
        "ui",
        "bool",
    ),
    _spec("ui_input", "ui.keyboardInput", InputArgs, "Type text into focused input.", "ui", "bool"),
    _spec("ui_clear", "ui.clearInput", NoArgs, "Clear focused input.", "ui", "bool"),
    *(
        _spec(
            "ui_" + name.lower(), "ui.press" + name, NoArgs, "Press " + name + " key.", "ui", "bool"
        )
        for name in ("Back", "Home", "Enter", "Power", "Menu")
    ),
    _spec("app_launch", "app.launch", PackageArgs, "Launch installed app.", "ui", "bool"),
    _spec(
        "app_is_installed",
        "app.isInstalled",
        PackageArgs,
        "Check whether app is installed; false is a valid answer.",
        "query",
        "bool",
    ),
    _spec(
        "app_install",
        "app.install",
        InstallArgs,
        "Install an APK/XAPK from a device path or safe HTTP(S) URL.",
        "system",
        "job",
    ),
    _spec("app_uninstall", "app.uninstall", PackageArgs, "Uninstall app.", "system", "job"),
    _spec("app_data_clear", "app.dataClear", PackageArgs, "Clear app user data.", "system", "job"),
    _spec(
        "app_data_backup",
        "app.dataBackup",
        BackupArgs,
        "Back up app data to device directory. Done/true only reflects dispatcher return, NOT independently verified backup artifact integrity.",
        "system",
        "job",
    ),
    _spec(
        "app_data_restore",
        "app.dataRestore",
        RestoreArgs,
        "Restore app data from device backup directory; return does not verify archive integrity.",
        "system",
        "job",
    ),
    _spec(
        "shell_exec",
        "shell.exec",
        ShellArgs,
        "Run explicitly permitted root shell command; unsafe, disabled by default.",
        "system",
        "shell",
    ),
    _spec(
        "network_start_proxy",
        "network.startProxy",
        ProxyArgs,
        "Start UID-scoped proxy or HTTPS capture.",
        "system",
        "job",
    ),
    _spec(
        "network_stop_proxy",
        "network.stopProxy",
        NoArgs,
        "Stop proxy and HTTPS capture.",
        "system",
        "job",
    ),
    _spec(
        "network_start_clash",
        "network.startClash",
        ClashArgs,
        "Start Clash from base64 UTF-8 config.",
        "system",
        "job",
    ),
    _spec("network_stop_clash", "network.stopClash", NoArgs, "Stop Clash.", "system", "job"),
    _spec(
        "job_poll",
        "job.poll",
        PollArgs,
        "Poll an opaque job handle from this client, not a raw Yuri ID.",
        "query",
        "job",
    ),
)
YURI_TOOLS: dict[str, YuriToolSpec] = {spec.name: spec for spec in _SPECS}
DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = tuple(
    spec.name for spec in _SPECS if spec.kind == "query"
) + ("yuri_click_text", "yuri_sub_click_text")


def _result(ok: bool, code: str, action: str, description: str, data: Any) -> dict[str, Any]:
    # Message is persisted into the model/trace by runners; never silently drop DATA.
    detail = json.dumps(data, ensure_ascii=False, default=str)
    return {
        "ok": ok,
        "code": code,
        "action": action,
        "message": f"{description} DATA: {detail}",
        "data": data,
    }


def _screen_coordinates(words: Any, x: int, y: int) -> Any:
    if words is None:
        return None
    if not isinstance(words, list):
        raise ValueError("OCR words must be an array or null")
    converted = []
    for word in words:
        if not isinstance(word, dict):
            raise ValueError("OCR word must be an object")
        converted.append(
            {
                **word,
                "x": word["x"] + x,
                "y": word["y"] + y,
                "rect": [[point[0] + x, point[1] + y] for point in word["rect"]],
            }
        )
    return converted


async def execute_yuri(
    client: YuriRpcClient, spec: YuriToolSpec, args: dict[str, Any]
) -> dict[str, Any]:
    """Validate before RPC and return an ActionResult-compatible structured result."""
    try:
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
        params = spec.args_schema.model_validate(args).model_dump(exclude_none=True)
    except (ValidationError, ValueError) as exc:
        return _result(
            False, "INVALID_ARGS", spec.name, "Invalid Yuri arguments.", {"error": str(exc)}
        )

    try:
        if spec.method in ("device.reset", "device.modify", "device.modifyProfile"):
            await client.ensure_farm_rom()
        if spec.method == "job.poll":
            data = await client.poll_job(params["job_id"])
        elif spec.result_kind == "job":
            data = await client.run_job(spec.method, params)
        else:
            data = await client.call(spec.method, params)
            if spec.result_kind == "screenshot":
                if not isinstance(data, str) or not data:
                    return _result(
                        False,
                        "SCREENSHOT_FAILED",
                        spec.name,
                        "Yuri did not return a screenshot path.",
                        data,
                    )
                data = {"path": await client.pull_screenshot(data)}
            elif spec.method == "recognition.subScreenGetText":
                data = _screen_coordinates(data, params["x"], params["y"])
    except YuriRpcError as exc:
        return _result(False, exc.code, spec.name, str(exc), exc.data)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return _result(
            False, "INVALID_RESPONSE", spec.name, "Unexpected Yuri response.", {"error": str(exc)}
        )

    if spec.result_kind == "job":
        if not isinstance(data, dict):
            return _result(False, "INVALID_RESPONSE", spec.name, "Invalid Yuri job response.", data)
        state = data.get("state")
        if state == "failed":
            return _result(False, "JOB_FAILED", spec.name, "Yuri job failed.", data)
        if state != "done":
            return _result(
                False,
                "JOB_PENDING" if state == "running" else "INVALID_RESPONSE",
                spec.name,
                "Yuri job is not complete." if state == "running" else "Invalid Yuri job state.",
                data,
            )
        if data.get("result") is False:
            return _result(False, "JOB_FAILED", spec.name, "Yuri job completed with false.", data)
        if data.get("result") is not True:
            return _result(
                False, "INVALID_RESPONSE", spec.name, "Yuri job returned no boolean outcome.", data
            )
        if spec.method == "app.dataBackup":
            return _result(
                True,
                "OK",
                spec.name,
                "Yuri backup dispatch returned; archive integrity was not verified.",
                data,
            )
    elif spec.result_kind == "shell":
        if not isinstance(data, dict) or type(data.get("status")) is not int:
            return _result(
                False, "INVALID_RESPONSE", spec.name, "Invalid Yuri shell response.", data
            )
        if data["status"] != 0:
            return _result(False, "SHELL_FAILED", spec.name, "Yuri shell command failed.", data)
    elif spec.result_kind == "bool" and spec.kind != "query" and data is not True:
        return _result(False, "ACTION_FAILED", spec.name, "Yuri action returned false.", data)
    return _result(True, "OK", spec.name, "Yuri RPC completed.", data)
