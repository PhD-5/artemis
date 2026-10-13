"""Task prompt substitution using only explicitly declared string arguments."""

from collections.abc import Iterator, Mapping
import re

_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*", re.ASCII)
# Escaped placeholders are consumed before active ones; the last branch catches
# unterminated placeholders instead of silently leaving them in the prompt.
_TOKEN = re.compile(r"\$\$\{[^}]*\}|\$\{([^}]*)\}|\$\{")


def _placeholder_names(goal: str) -> Iterator[str]:
    for token in _TOKEN.finditer(goal):
        if token[0].startswith("$$"):
            continue
        name = token[1]
        if name is None:
            raise ValueError("Unterminated placeholder in goal")
        if not _PARAMETER_NAME.fullmatch(name):
            raise ValueError(f"Invalid placeholder name: {name!r}")
        yield name


def validate_task_template(goal: str, parameters: list[str]) -> None:
    declared: set[str] = set()
    for name in parameters:
        if not _PARAMETER_NAME.fullmatch(name):
            raise ValueError(f"Invalid parameter name: {name!r}")
        if name in declared:
            raise ValueError(f"Duplicate parameter: {name}")
        declared.add(name)
    for name in _placeholder_names(goal):
        if name not in declared:
            raise ValueError(f"Undeclared parameter in goal: {name}")


def infer_task_template_parameters(goal: str) -> list[str]:
    """Upgrade legacy prompts to ordered, unique parameter declarations."""
    return list(dict.fromkeys(_placeholder_names(goal)))


def render_task_template(goal: str, parameters: list[str], args: Mapping[str, str]) -> str:
    """Render a validated preset once; argument contents are never interpreted."""
    missing = [name for name in parameters if name not in args]
    if missing:
        raise ValueError(f"Missing template arguments: {', '.join(missing)}")
    unknown = sorted(args.keys() - set(parameters))
    if unknown:
        raise ValueError(f"Unknown template arguments: {', '.join(unknown)}")
    for name, value in args.items():
        if not isinstance(value, str):
            raise ValueError(f"Template argument {name} must be a string")

    def replace(token: re.Match[str]) -> str:
        if token[0].startswith("$$"):
            return token[0][1:]
        return args[token[1]]

    return _TOKEN.sub(replace, goal)
