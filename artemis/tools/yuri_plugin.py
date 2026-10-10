"""Task-scoped adapters for the optional Yuri capability catalogue.

Only prepare_task_yuri imports this module. Query helpers and turn-ending
mutations share the same RPC/MCP execution and structured business results.
"""

import inspect
import json
from typing import Any

from langchain_core.tools import StructuredTool
from mcp.types import CallToolResult, TextContent

from artemis.clients.yuri_rpc_client import YuriRpcClient
from artemis.config.yuri import YuriConfig
from artemis.core.tool_declaration import ToolDeclaration
from artemis.core.tool_failure import ToolFailure
from artemis.mcp.action_types import ActionResult
from artemis.tools.base import _flatten_json_schema_properties
from artemis.tools.yuri import DEFAULT_ALLOWED_TOOLS, YURI_TOOLS, execute_yuri


class YuriPlugin:
    def __init__(self, ctx: Any, config: YuriConfig, profile: str | None = None):
        self.role = "flash" if str(profile).lower() == "flash" else "operator"
        self.ctx = ctx
        self.client = YuriRpcClient(ctx, config)
        names = DEFAULT_ALLOWED_TOOLS if config.allowed_tools is None else config.allowed_tools
        unknown = set(names) - YURI_TOOLS.keys()
        if unknown:
            raise ValueError(f"Unknown Yuri tools in allowed_tools: {sorted(unknown)}")
        self.specs = {name: YURI_TOOLS[name] for name in names}
        if not self.specs:
            raise ValueError("Yuri was requested, but no Yuri tools are permitted.")
        self.active = False
        self._original_actuator = None

    def install(self) -> None:
        from artemis.mcp.actuators.adb import AdbActuator
        from artemis.mcp.actuators.yuri import YuriActuator

        if self.ctx.action_session is not None or self.ctx.yuri_plugin is not None:
            raise RuntimeError(
                "Yuri must be installed once, before creating the task action session."
            )
        self._original_actuator = self.ctx.actuator
        backend = self.ctx.actuator or AdbActuator(self.ctx)
        self.ctx.actuator = YuriActuator(backend, self)
        self.ctx.yuri_plugin = self
        self.active = True

    def permits(self, name: str, role: str) -> bool:
        if not self.active or name not in self.specs:
            return False
        deny = getattr(self.ctx.agent_config, "denylisted_tools", {}) or {}
        if name in deny.get(role, []):
            return False
        # Pro mutation declarations must not promise a tool its Validator denies.
        if role == "operator" and self.specs[name].kind != "query":
            return name not in deny.get("validator", [])
        return True

    def action_names(self, role: str) -> frozenset[str]:
        return frozenset(
            name
            for name, spec in self.specs.items()
            if spec.kind != "query" and self.permits(name, role)
        )

    def query_names(self, role: str) -> frozenset[str]:
        return frozenset(
            name
            for name, spec in self.specs.items()
            if spec.kind == "query" and self.permits(name, role)
        )

    def validate_args(self, name: str, args: dict[str, Any], role: str) -> dict[str, Any]:
        if not self.permits(name, role):
            raise ValueError(f"Yuri tool '{name}' is not permitted for {role} in this task.")
        params = self.specs[name].args_schema.model_validate(args).model_dump(exclude_none=True)
        width = self.ctx.device.device_width
        height = self.ctx.device.device_height
        for x_key, y_key in (("x", "y"), ("fromX", "fromY"), ("toX", "toY")):
            if x_key in params and y_key in params:
                if not (0 <= params[x_key] < width and 0 <= params[y_key] < height):
                    raise ValueError(
                        f"Yuri {x_key}/{y_key} must be inside the device's {width}x{height} pixel screen."
                    )
        if "w" in params and "h" in params:
            if params["x"] + params["w"] > width or params["y"] + params["h"] > height:
                raise ValueError("Yuri OCR region extends outside the device screen.")
        return params

    @staticmethod
    def failure(name: str, message: str, code: str = "INVALID_ARGS") -> dict[str, Any]:
        return {"ok": False, "code": code, "action": name, "message": message, "data": None}

    async def execute_local(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        # Direct MCP calls cannot bypass the task's configured whitelist.
        role = self.role
        try:
            params = self.validate_args(name, args, role)
        except ValueError as exc:
            return self.failure(name, str(exc))
        payload = await execute_yuri(self.client, self.specs[name], params)
        # Keep Yuri's diagnostic code, while meeting the existing action result
        # contract; no changes to ordinary extensions or global ActionResult.
        payload["yuri_code"] = payload["code"]
        known_codes = {
            "OK",
            "INVALID_ARGS",
            "TARGET_NOT_FOUND",
            "DEVICE_ERROR",
            "PACKAGE_NOT_FOUND",
            "TIMEOUT",
            "UNSUPPORTED",
        }
        if payload["code"] not in known_codes:
            payload["code"] = (
                "TIMEOUT"
                if payload["code"] in {"JOB_PENDING", "RPC_TIMEOUT", "JOB_TIMEOUT"}
                else "INVALID_ARGS"
                if payload["code"] == "BAD_ARGS"
                else "DEVICE_ERROR"
            )
        return payload

    async def call(
        self, session: Any, name: str, args: dict[str, Any], role: str
    ) -> dict[str, Any]:
        try:
            params = self.validate_args(name, args, role)
            result = await session.call_raw(name, params)
            payload = result.structuredContent
            ActionResult.model_validate(payload)
            return payload
        except Exception as exc:
            return self.failure(name, str(exc), "DEVICE_ERROR")

    def declarations(self, role: str) -> list[ToolDeclaration]:
        declarations = []
        for name, spec in self.specs.items():
            if self.permits(name, role):
                properties, required = _flatten_json_schema_properties(
                    spec.args_schema.model_json_schema()
                )
                declarations.append(
                    ToolDeclaration(
                        name=name,
                        description=spec.description,
                        parameters={
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    )
                )
        return declarations

    def langchain_tools(self) -> list[StructuredTool]:
        tools = []
        for name, spec in self.specs.items():
            if not self.permits(name, "operator"):
                continue
            if spec.kind == "query":
                handler = self._query_handler(name)
                tools.append(
                    StructuredTool(
                        name=name,
                        description=spec.description,
                        args_schema=spec.args_schema,
                        coroutine=handler,
                    )
                )
            else:

                def record_action(_name=name, **kwargs):
                    return json.dumps(
                        {"action": _name, "args": self.validate_args(_name, kwargs, "operator")}
                    )

                tools.append(
                    StructuredTool(
                        name=name,
                        description=spec.description,
                        args_schema=spec.args_schema,
                        func=record_action,
                    )
                )
        return tools

    def _query_handler(self, name: str):
        async def query(**kwargs):
            from artemis.mcp.action_session import get_action_session

            session = await get_action_session(self.ctx)
            result = await self.call(session, name, kwargs, "operator")
            return result["message"] if result["ok"] else ToolFailure(result["message"])

        return query

    def wire_handler(self, name: str):
        async def handler(**kwargs) -> CallToolResult:
            payload = await self.execute_local(name, kwargs)
            return CallToolResult(
                content=[TextContent(type="text", text=payload["message"])],
                structuredContent=payload,
                isError=False,
            )

        spec = self.specs[name]
        parameters = []
        annotations = {"return": CallToolResult}
        for field_name, field in spec.args_schema.model_fields.items():
            annotation = field.rebuild_annotation()
            annotations[field_name] = annotation
            parameters.append(
                inspect.Parameter(
                    field_name,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=annotation,
                    default=inspect.Parameter.empty if field.is_required() else field.default,
                )
            )
        handler.__name__ = name
        handler.__annotations__ = annotations
        setattr(
            handler,
            "__signature__",
            inspect.Signature(parameters, return_annotation=CallToolResult),
        )
        return handler

    async def aclose(self) -> None:
        self.active = False
        try:
            await self.client.aclose()
        finally:
            if self.ctx.yuri_plugin is self:
                self.ctx.yuri_plugin = None
                self.ctx.actuator = self._original_actuator
