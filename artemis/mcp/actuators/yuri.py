"""Add Yuri RPC tools without replacing the task's existing actuator."""

from typing import Any

from artemis.mcp.action_manifest import ExtensionTool


class YuriActuator:
    def __init__(self, backend: Any, plugin: Any):
        self.backend = backend
        self.plugin = plugin
        self.controller = backend.controller

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)

    def capabilities(self) -> frozenset[str]:
        return self.backend.capabilities()

    def extensions(self) -> list[ExtensionTool]:
        # Yuri query/action classification is plugin-local; do not change the
        # legacy extension contract or duplicate automatic model declarations.
        return [
            *self.backend.extensions(),
            *[
                ExtensionTool(
                    name=name,
                    description=spec.description,
                    input_schema=spec.args_schema.model_json_schema(),
                    handler=self.plugin.wire_handler(name),
                    targets=frozenset(),
                )
                for name, spec in self.plugin.specs.items()
            ],
        ]
