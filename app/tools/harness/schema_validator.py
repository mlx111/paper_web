"""Schema validator — type checking and coercion for tool arguments.

Provides lightweight argument validation with automatic type coercion
(e.g., "5" → 5) so the healing loop can fix simple parameter errors
without an LLM round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ArgSpec:
    """Specification for a single tool argument."""

    name: str
    type: type  # str / int / float / bool
    required: bool = True
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    enum: tuple[str, ...] | None = None
    description: str = ""


@dataclass
class ArgError:
    """A single validation error."""

    field: str
    code: str  # MISSING / WRONG_TYPE / OUT_OF_RANGE / UNKNOWN_FIELD / INVALID_ENUM
    message: str
    got: Any = None


@dataclass
class ValidationResult:
    """Result of validating tool arguments."""

    ok: bool
    errors: list[ArgError] = field(default_factory=list)
    coerced_args: dict[str, Any] = field(default_factory=dict)


class ToolSchema:
    """Schema definition and validator for a tool's arguments."""

    def __init__(self, tool_name: str, specs: list[ArgSpec]):
        self.tool_name = tool_name
        self._specs = {s.name: s for s in specs}

    @property
    def spec_names(self) -> set[str]:
        return set(self._specs.keys())

    def validate(self, args: dict[str, Any]) -> ValidationResult:
        """Validate *args* against the schema, with type coercion."""
        errors: list[ArgError] = []
        coerced: dict[str, Any] = {}

        # Check known fields
        for name, spec in self._specs.items():
            if name not in args:
                if spec.required:
                    if spec.default is not None:
                        coerced[name] = spec.default
                    else:
                        errors.append(ArgError(
                            field=name, code="MISSING",
                            message=f"Missing required argument: {name}",
                        ))
                elif spec.default is not None:
                    coerced[name] = spec.default
                continue

            raw = args[name]
            # Type coercion
            coerced_val = self._coerce(raw, spec)
            if coerced_val is None and raw is not None:
                errors.append(ArgError(
                    field=name, code="WRONG_TYPE",
                    message=f"Expected {spec.type.__name__} for '{name}', got {type(raw).__name__}: {raw!r}",
                    got=raw,
                ))
                continue

            # Range check
            if spec.min_value is not None and isinstance(coerced_val, (int, float)):
                if coerced_val < spec.min_value:
                    errors.append(ArgError(
                        field=name, code="OUT_OF_RANGE",
                        message=f"'{name}'={coerced_val} is below minimum {spec.min_value}",
                        got=raw,
                    ))
                    continue
            if spec.max_value is not None and isinstance(coerced_val, (int, float)):
                if coerced_val > spec.max_value:
                    errors.append(ArgError(
                        field=name, code="OUT_OF_RANGE",
                        message=f"'{name}'={coerced_val} exceeds maximum {spec.max_value}",
                        got=raw,
                    ))
                    continue

            # Enum check
            if spec.enum and coerced_val not in spec.enum:
                errors.append(ArgError(
                    field=name, code="INVALID_ENUM",
                    message=f"'{name}'='{coerced_val}' not in {spec.enum}",
                    got=raw,
                ))
                continue

            coerced[name] = coerced_val

        # Check for unknown fields
        for key in args:
            if key not in self._specs:
                errors.append(ArgError(
                    field=key, code="UNKNOWN_FIELD",
                    message=f"Unknown argument: {key}",
                    got=args[key],
                ))

        return ValidationResult(
            ok=len(errors) == 0,
            errors=errors,
            coerced_args=coerced,
        )

    @staticmethod
    def _coerce(value: Any, spec: ArgSpec) -> Any:
        """Attempt to coerce *value* to the spec's type. Returns None on failure."""
        if value is None:
            return None
        if isinstance(value, spec.type):
            return value
        # String → int/float/bool
        if spec.type == int:
            if isinstance(value, str):
                try:
                    # Handle "five" → can't coerce, return None
                    return int(value)
                except ValueError:
                    return None
            if isinstance(value, float):
                return int(value)
        elif spec.type == float:
            if isinstance(value, (int, str)):
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
        elif spec.type == bool:
            if isinstance(value, str):
                lower = value.strip().lower()
                if lower in ("true", "yes", "1"):
                    return True
                if lower in ("false", "no", "0"):
                    return False
                return None
            if isinstance(value, int):
                return bool(value)
        elif spec.type == str:
            return str(value)
        return None

    def describe(self) -> str:
        """Human-readable schema description for LLM repair prompts."""
        lines = [f"Tool: {self.tool_name}"]
        for name, spec in self._specs.items():
            req = "required" if spec.required else "optional"
            default = f", default={spec.default}" if spec.default is not None else ""
            enum = f", enum={spec.enum}" if spec.enum else ""
            desc = f"  - {name}: {spec.type.__name__} ({req}{default}{enum})"
            if spec.description:
                desc += f" — {spec.description}"
            lines.append(desc)
        return "\n".join(lines)


# ─── Schema definitions for existing tools ──────────────────────────────

SCHEMAS: dict[str, list[ArgSpec]] = {
    "web_search": [
        ArgSpec("query", str, required=True, description="search query"),
        ArgSpec("count", int, required=False, default=5, min_value=1, max_value=20),
    ],
    "academic_search_papers": [
        ArgSpec("query", str, required=True, description="search keywords"),
        ArgSpec("result_limit", int, required=False, default=5, min_value=1, max_value=20),
        ArgSpec("min_year", int, required=False, default=None, min_value=1900, max_value=2100),
    ],
    "get_paper_abstract": [
        ArgSpec("url", str, required=True, description="paper URL"),
        ArgSpec("title", str, required=True, description="paper title"),
    ],
    "get_paper_bibtex": [
        ArgSpec("url", str, required=True),
        ArgSpec("title", str, required=True),
    ],
    "search_github_repos": [
        ArgSpec("query", str, required=True),
        ArgSpec("result_limit", int, required=False, default=5, min_value=1, max_value=20),
    ],
    "review_paper_quality": [
        ArgSpec("paper_text", str, required=True),
        ArgSpec("title", str, required=False, default=""),
    ],
    "build_citation_pool": [
        ArgSpec("topic", str, required=True),
        ArgSpec("max_papers", int, required=False, default=5, min_value=1, max_value=20),
        ArgSpec("engine", str, required=False, default="semantic"),
        ArgSpec("include_bibtex", bool, required=False, default=True),
    ],
    "retrieve_knowledge": [
        ArgSpec("query", str, required=True, description="knowledge base query"),
    ],
    "get_current_time": [
        ArgSpec("timezone", str, required=False, default="Asia/Shanghai"),
    ],
    "extract_document_text": [
        ArgSpec("file_path", str, required=True),
        ArgSpec("summary_length", int, required=False, default=5000, min_value=100, max_value=50000),
    ],
    "send_email": [
        ArgSpec("to", str, required=True, description="recipient email"),
        ArgSpec("subject", str, required=True, description="email subject"),
        ArgSpec("body", str, required=True, description="email body"),
    ],
}


def get_schema(tool_name: str) -> ToolSchema | None:
    """Get the schema for a tool, or None if not defined."""
    specs = SCHEMAS.get(tool_name)
    if specs is None:
        return None
    return ToolSchema(tool_name, specs)
