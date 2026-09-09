"""Guardrails — input-side prompt injection detection and output-side filtering.

Provides a lightweight, regex-based detection layer that runs before and
after tool execution to block injection attempts and sanitize tool output.
No LLM calls — all checks are deterministic for low latency.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from typing import Any

from ..tool_result import ToolResult
from .policy import ToolPolicy, default_policy


@dataclass
class InjectionReport:
    """Result of an injection check."""

    risk_score: float = 0.0
    matched_patterns: list[str] = field(default_factory=list)
    blocked: bool = False


class InjectionDetector:
    """Regex-based prompt-injection detector.

    Five categories of attack patterns:
    1. Instruction override (ignore/disregard previous instructions)
    2. Role hijack (you are now / act as)
    3. System command injection (os.system, eval, subprocess)
    4. Credential theft (api_key=, token=, secret=)
    5. Cross-tool data poisoning (tool output containing new instructions)
    """

    INJECTION_PATTERNS: list[tuple[str, float]] = [
        # 1. Instruction override
        (r"(?i)\b(ignore|disregard)\b.{0,30}\b(previous|above|prior|system)\b.{0,30}(instruction|prompt|rule|message)", 0.9),
        (r"(?i)\bforget\s+(all|your|previous)\b", 0.85),
        # 2. Role hijack
        (r"(?i)\byou\s+are\s+(now|actually)\b", 0.8),
        (r"(?i)\bact\s+as\s+(if|a)\b.{0,20}(admin|root|developer|system)", 0.85),
        (r"(?i)\bas\s+an?\s+(ai|assistant)\b.{0,30}\b(call|invoke|use|execute)\b.{0,20}(tool|function|command)", 0.8),
        # 3. System command injection
        (r"(?i)\b(eval|exec)\s*\(", 0.95),
        (r"(?i)\b(sub?_?process|os\.system|os\.popen|/bin/sh|/bin/bash)\b", 0.95),
        # 4. Credential theft
        (r"(?i)\b(api_key|api_secret|token|secret|password|authorization)\s*[:=]\s*\S", 0.7),
        # 5. Instruction in tool output
        (r"(?i)\b(ignore|disregard).{0,20}(result|output|above).{0,20}(and|then|please).{0,30}(call|invoke|use|send)", 0.9),
    ]

    # Compiled patterns for performance
    _compiled: list[tuple[re.Pattern, float]] | None = None

    @classmethod
    def _get_compiled(cls) -> list[tuple[re.Pattern, float]]:
        if cls._compiled is None:
            cls._compiled = [(re.compile(p), s) for p, s in cls.INJECTION_PATTERNS]
        return cls._compiled

    def detect(self, text: str, source: str = "args") -> InjectionReport:
        """Check *text* for injection patterns.

        Args:
            text: The text to check.
            source: "args" for input-side, "tool_output" for output-side.

        Returns:
            InjectionReport with risk_score and matched patterns.
        """
        if not text or not isinstance(text, str):
            return InjectionReport()

        matched: list[str] = []
        max_score = 0.0

        for pattern, score in self._get_compiled():
            if pattern.search(text):
                matched.append(pattern.pattern[:60])
                max_score = max(max_score, score)

        # Also check for unusually long instruction-like text in args
        if source == "args" and len(text) > 500:
            instruction_keywords = re.findall(
                r"(?i)\b(please|must|should|require|important|notice|warning)\b", text
            )
            if len(instruction_keywords) > 5:
                max_score = max(max_score, 0.6)
                matched.append("excessive_instruction_keywords")

        blocked = max_score >= 0.7
        return InjectionReport(
            risk_score=round(max_score, 2),
            matched_patterns=matched,
            blocked=blocked,
        )


class GuardrailChain:
    """Pre/post execution guardrail chain for tool calls."""

    def __init__(
        self,
        injection_detector: InjectionDetector | None = None,
        tool_policy: ToolPolicy | None = None,
    ):
        self.detector = injection_detector or InjectionDetector()
        self.policy = tool_policy or default_policy

    def pre_check(
        self,
        tool_name: str,
        args: dict[str, Any],
        session_id: str = "",
    ) -> ToolResult | None:
        """Run before tool execution. Returns ToolResult if blocked, None if pass."""
        # 1. Authorization check
        if not self.policy.is_authorized(tool_name, session_id):
            return ToolResult.failure(
                f"Tool '{tool_name}' is not authorized for this session",
                "UNAUTHORIZED_TOOL",
            )

        # 2. Input injection detection
        for key, value in args.items():
            if not isinstance(value, str):
                continue
            report = self.detector.detect(value, source="args")
            if report.blocked:
                return ToolResult.failure(
                    f"Possible prompt injection detected in argument '{key}' "
                    f"(risk_score={report.risk_score}). "
                    f"Matched: {', '.join(report.matched_patterns[:3])}",
                    "INJECTION_DETECTED",
                )

        return None  # pass

    def post_check(self, tool_name: str, result: ToolResult) -> ToolResult:
        """Run after tool execution. Sanitize output for injection."""
        if not result.ok or result.data is None:
            return result

        # Serialize data to string for checking
        try:
            data_str = json.dumps(result.data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            data_str = str(result.data)

        report = self.detector.detect(data_str, source="tool_output")
        if report.blocked:
            # Replace suspicious content with filtered marker
            filtered_data = self._sanitize(data_str, report.matched_patterns)
            result.data = {"filtered_output": filtered_data, "original_blocked": True}
            result.summary = f"[{tool_name}] output filtered: possible injection (score={report.risk_score})"
            # Attach guardrail metadata
            if not hasattr(result, "_meta"):
                result._meta = {}
            result._meta["guardrail_post"] = {
                "blocked": True,
                "risk_score": report.risk_score,
                "matched_patterns": report.matched_patterns[:3],
            }

        return result

    @staticmethod
    def _sanitize(text: str, patterns: list[str]) -> str:
        """Replace suspicious content with [filtered] markers."""
        result = text
        for pattern_str in patterns[:3]:
            try:
                compiled = re.compile(pattern_str)
                result = compiled.sub("[filtered: possible injection]", result)
            except re.error:
                continue
        # Truncate if too long after filtering
        if len(result) > 2000:
            result = result[:2000] + "...[truncated]"
        return result
