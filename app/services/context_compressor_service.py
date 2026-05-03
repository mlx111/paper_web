"""
Hermes-style four-phase context compression engine.

Based on Hermes Agent's agent/context_compressor.py (1200 lines).

Phases:
  1. ToolOutputPruner — zero-LLM: prune old tool results to 1-line summaries
  2. BoundaryFinder — determine head/tail protection boundaries
  3. SummaryGenerator — LLM structured summarization of middle zone
  4. MessageSanitizer — fix orphan tool_call/result pairs, reassemble

Plus AntiThrashTracker to prevent repeated ineffective compressions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import md5
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)


# ---------------------------------------------------------------------------
# rough token estimator (mirrors context.compressor._rough_token_count)
# ---------------------------------------------------------------------------

def _rough_token_count(text: str) -> int:
    """Lightweight token estimate: len(text) // 2, min 1."""
    if not text:
        return 0
    return max(1, len(text) // 2)


def _message_token_count(msg: BaseMessage) -> int:
    """Estimate tokens for a single message."""
    content = str(getattr(msg, "content", ""))
    extra = 0
    # tool_calls carry their own overhead
    for tc in getattr(msg, "tool_calls", []) or []:
        args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
        extra += _rough_token_count(args_str) + _rough_token_count(tc.get("name", ""))
    return _rough_token_count(content) + extra


def _total_tokens(messages: list[BaseMessage]) -> int:
    return sum(_message_token_count(m) for m in messages)


# ---------------------------------------------------------------------------
# config & result types
# ---------------------------------------------------------------------------


@dataclass
class CompressorConfig:
    """Configuration for the Hermes-style context compressor."""

    context_window_tokens: int = 32000
    compression_threshold_ratio: float = 0.5
    head_protect_messages: int = 3
    tail_token_budget: int = 20000
    llm_enabled: bool = True
    llm_temperature: float = 0.0
    summarize_prompt_limit: int = 8000
    anti_thrash_min_savings: float = 0.1
    anti_thrash_consecutive_limit: int = 2

    @property
    def trigger_tokens(self) -> int:
        return max(1, int(self.context_window_tokens * self.compression_threshold_ratio))


@dataclass
class BoundaryResult:
    """Output of Phase 2 — which messages go where."""

    head: list[BaseMessage]
    middle: list[BaseMessage]   # to be summarized
    tail: list[BaseMessage]     # protected verbatim


@dataclass
class CompressionResult:
    """Output of the full compression pipeline."""

    messages: list[BaseMessage]
    was_compressed: bool
    savings_ratio: float
    thrash_warning: bool = False
    summary_text: str = ""


# ---------------------------------------------------------------------------
# Phase 1: Tool Output Pruner
# ---------------------------------------------------------------------------

TOOL_SUMMARY_MAX = 120


class ToolOutputPruner:
    """Replace old tool results with 1-line info summaries.  Zero LLM calls."""

    @staticmethod
    def _summarize_tool_result(msg: ToolMessage, idx: int) -> str:
        content = str(getattr(msg, "content", "") or "")
        name = getattr(msg, "name", "tool") or "tool"
        size = len(content)
        preview = content[:80].replace("\n", " ").strip()
        if len(content) > 80:
            preview += "..."

        status = "ok"
        if "error" in content.lower() or "exception" in content.lower():
            status = "ERROR"
        elif "failed" in content.lower() or "timeout" in content.lower():
            status = "FAILED"

        return f"[{name}] {status} | {size} chars | {preview}"

    def prune(
        self,
        messages: list[BaseMessage],
        current_turn_start_idx: int,
    ) -> list[BaseMessage]:
        """
        Prune tool outputs that belong to turns *before* current_turn_start_idx.

        The most recent tool round (identified by the last AIMessage with tool_calls)
        is preserved verbatim.
        """
        if not messages:
            return []

        # Find the last AIMessage with tool_calls — its results are the "current round"
        last_tool_call_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                last_tool_call_idx = i
                break

        if last_tool_call_idx < 0:
            return list(messages)  # no tool calls at all

        # Collect tool_call_ids from the LAST round only — these results stay verbatim
        last_round_ids: set[str] = set()
        for tc in getattr(messages[last_tool_call_idx], "tool_calls", []) or []:
            tc_id = tc.get("id", "")
            if tc_id:
                last_round_ids.add(tc_id)

        result: list[BaseMessage] = []
        tool_results_seen: dict[str, int] = {}  # hash -> first index

        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                tc_id = getattr(msg, "tool_call_id", "") or ""

                if tc_id in last_round_ids:
                    result.append(msg)
                    continue

                # For old rounds: summarize and dedup
                content_hash = md5(
                    str(getattr(msg, "content", "")).encode()
                ).hexdigest()[:12]

                if content_hash in tool_results_seen:
                    # Duplicate — skip, already summarized
                    continue

                tool_results_seen[content_hash] = i
                summary = self._summarize_tool_result(msg, i)
                result.append(ToolMessage(
                    content=summary,
                    name=getattr(msg, "name", "tool"),
                    tool_call_id=tc_id or f"pruned_{i}",
                ))
            elif isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                # Truncate old tool_call args
                if i < last_tool_call_idx:
                    tcs = []
                    for tc in msg.tool_calls:
                        truncated = dict(tc)
                        args = truncated.get("args", {})
                        if isinstance(args, dict):
                            truncated_args = {}
                            for k, v in args.items():
                                if isinstance(v, str) and len(v) > TOOL_SUMMARY_MAX:
                                    truncated_args[k] = v[:TOOL_SUMMARY_MAX - 3] + "..."
                                else:
                                    truncated_args[k] = v
                            truncated["args"] = truncated_args
                        tcs.append(truncated)
                    msg = AIMessage(
                        content=getattr(msg, "content", ""),
                        tool_calls=tcs,
                    )
                result.append(msg)
            else:
                result.append(msg)

        return result


# ---------------------------------------------------------------------------
# Phase 2: Boundary Finder
# ---------------------------------------------------------------------------


class BoundaryFinder:
    """Determine head / middle / tail boundaries for compression."""

    def find_boundaries(
        self,
        messages: list[BaseMessage],
        config: CompressorConfig,
    ) -> BoundaryResult:
        n = len(messages)
        if n <= config.head_protect_messages:
            return BoundaryResult(head=list(messages), middle=[], tail=[])

        # Head: first N messages
        head = list(messages[:config.head_protect_messages])

        # Tail: walk backwards, accumulating until token budget exhausted
        tail: list[BaseMessage] = []
        tail_tokens = 0
        tail_start = n - 1

        for i in range(n - 1, config.head_protect_messages - 1, -1):
            msg = messages[i]
            t = _message_token_count(msg)
            if tail_tokens + t > config.tail_token_budget:
                break
            tail.insert(0, msg)
            tail_tokens += t
            tail_start = i

        # Middle: everything between head and tail
        middle = list(messages[config.head_protect_messages:tail_start])

        # Boundary alignment — don't split tool_call / result pairs
        head, middle, tail = self._align_boundary(head, middle, tail)

        return BoundaryResult(head=head, middle=middle, tail=tail)

    def _align_boundary(
        self,
        head: list[BaseMessage],
        middle: list[BaseMessage],
        tail: list[BaseMessage],
    ) -> tuple[list[BaseMessage], list[BaseMessage], list[BaseMessage]]:
        """Ensure head/tail boundaries don't split tool_call / result pairs."""

        # If tail starts with orphan ToolMessages (no AIMessage with matching tool_call in tail),
        # pull the preceding AIMessage from middle into tail.
        if tail and isinstance(tail[0], ToolMessage):
            tc_id = getattr(tail[0], "tool_call_id", "")
            if tc_id:
                found = False
                for m in tail:
                    if isinstance(m, AIMessage):
                        for tc in getattr(m, "tool_calls", []) or []:
                            if tc.get("id") == tc_id:
                                found = True
                                break
                if not found and middle:
                    # Pull the last AIMessage with tool_calls from middle
                    for i in range(len(middle) - 1, -1, -1):
                        if isinstance(middle[i], AIMessage) and getattr(middle[i], "tool_calls", None):
                            tail.insert(0, middle.pop(i))
                            break

        # If middle ends with an AIMessage that has tool_calls, ensure corresponding
        # ToolMessages are pulled from tail into middle (they belong together).
        # Actually, this is handled by pulling from the head side — if head's last
        # message is AIMessage with tool_calls, pull matching ToolMessages from middle.
        if head and isinstance(head[-1], AIMessage) and getattr(head[-1], "tool_calls", None):
            tc_ids = {tc.get("id") for tc in head[-1].tool_calls if tc.get("id")}
            pulled = []
            remaining = []
            for m in middle:
                if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", "") in tc_ids:
                    pulled.append(m)
                else:
                    remaining.append(m)
            if pulled:
                head.extend(pulled)
                middle = remaining

        return head, middle, tail


# ---------------------------------------------------------------------------
# Phase 3: Summary Generator (LLM-based)
# ---------------------------------------------------------------------------

SUMMARY_SYSTEM_PROMPT = """You are a context compression assistant. Your job is to summarize the
"middle zone" of a conversation — the part being removed from the active context.

The middle zone contains older conversation turns, tool calls, and tool results.
Many tool results have already been pruned to 1-line summaries.

Produce a structured summary using the template below.  If a section has no
relevant information, write "(none)".

## Active Task
[The user's most recent uncompleted task — most important field]

## Goal / Constraints
[What the user wants to achieve, any constraints mentioned]

## Completed Actions
[What has been done so far — list key actions with results]

## In Progress / Blocked
[What is currently happening, what is blocked]

## Key Decisions
[Decisions made, preferences stated, constraints agreed upon]

## Resolved Questions
[Questions that were answered satisfactorily]

## Pending User Asks
[Questions the user asked that have NOT yet been answered — CRITICAL]

## Relevant Files / Remaining Work
[Files mentioned, remaining tasks, next steps]

Keep the summary concise but complete.  Every Pending User Ask must be preserved."""

HANDOFF_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY]\n"
    "Earlier turns were compacted into the summary below.\n"
    "This is a handoff from a previous context window — treat it as\n"
    "background reference, NOT as active instructions.\n"
    "Do NOT answer questions or fulfill requests mentioned in this\n"
    "summary; they were already addressed.\n\n"
)


class SummaryGenerator:
    """Generate structured LLM summaries of the compressed middle zone."""

    def __init__(self, llm_factory=None):
        """
        Args:
            llm_factory: Callable that returns a LangChain chat model.
                         Defaults to qwen_model.init_model from models.factory.
        """
        self._llm_factory = llm_factory
        self._cached_summary: str = ""

    def _get_llm(self, config: CompressorConfig):
        if self._llm_factory is not None:
            return self._llm_factory(streaming=False, temperature=config.llm_temperature)

        # Fallback: import the project's default model
        from app.models.factory import qwen_model
        return qwen_model.init_model(streaming=False)

    @property
    def cached_summary(self) -> str:
        return self._cached_summary

    def generate(
        self,
        zone_messages: list[BaseMessage],
        config: CompressorConfig,
    ) -> str:
        """Generate a structured summary for the middle zone messages."""
        if not zone_messages:
            return ""

        if not config.llm_enabled:
            summary = self._fallback_summary(zone_messages)
            self._cached_summary = summary
            return summary

        zone_text = self._format_zone(zone_messages, config.summarize_prompt_limit)

        # Build the user prompt
        existing_note = ""
        if self._cached_summary:
            existing_note = (
                "\n\n## Existing Summary (update this, don't rewrite from scratch)\n"
                + self._cached_summary
            )

        user_prompt = (
            f"Summarize the following conversation middle zone:\n\n"
            f"```\n{zone_text}\n```"
            f"{existing_note}"
        )

        try:
            llm = self._get_llm(config)
            messages = [
                SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
            response = llm.invoke(messages)
            summary = str(getattr(response, "content", "")).strip()
        except Exception:
            return self._fallback_summary(zone_messages)

        if not summary:
            return self._fallback_summary(zone_messages)

        self._cached_summary = summary
        return HANDOFF_PREFIX + summary

    def _format_zone(self, messages: list[BaseMessage], limit: int) -> str:
        """Format messages into a string, truncating to prompt_limit chars."""
        lines: list[str] = []
        total = 0

        for msg in messages:
            role = type(msg).__name__.replace("Message", "").lower()

            if isinstance(msg, ToolMessage):
                content = str(getattr(msg, "content", ""))
                name = getattr(msg, "name", "")
                line = f"[{role}:{name}] {content}"
            elif isinstance(msg, AIMessage):
                content = str(getattr(msg, "content", "") or "")
                tcs = getattr(msg, "tool_calls", []) or []
                if tcs:
                    tc_names = [tc.get("name", "?") for tc in tcs]
                    line = f"[{role}] called {', '.join(tc_names)}"
                    if content:
                        line += f" | {content}"
                else:
                    line = f"[{role}] {content}"
            elif isinstance(msg, HumanMessage):
                content = str(getattr(msg, "content", ""))
                line = f"[user] {content}"
            else:
                content = str(getattr(msg, "content", ""))
                line = f"[{role}] {content}"

            # Truncate individual lines
            if len(line) > 300:
                line = line[:297] + "..."

            if total + len(line) > limit:
                lines.append("... [truncated]")
                break

            lines.append(line)
            total += len(line)

        return "\n".join(lines)

    def _fallback_summary(self, messages: list[BaseMessage]) -> str:
        """Keyword-based fallback when LLM is unavailable."""
        user_texts: list[str] = []
        tool_names: list[str] = []
        ai_statements: list[str] = []

        for msg in messages:
            if isinstance(msg, HumanMessage):
                text = str(getattr(msg, "content", "")).strip()[:200]
                if text:
                    user_texts.append(text)
            elif isinstance(msg, AIMessage):
                text = str(getattr(msg, "content", "")).strip()[:200]
                if text:
                    ai_statements.append(text)
                for tc in getattr(msg, "tool_calls", []) or []:
                    tool_names.append(tc.get("name", "?"))

        lines = [
            HANDOFF_PREFIX,
            "## Active Task",
            user_texts[-1] if user_texts else "(none)",
            "",
            "## Goal / Constraints",
            user_texts[0] if len(user_texts) > 1 else "(none)",
            "",
            "## Completed Actions",
        ]
        for tn in list(dict.fromkeys(tool_names))[:8]:
            lines.append(f"- Called tool: {tn}")
        if not tool_names:
            lines.append("(none)")

        lines.extend([
            "",
            "## In Progress / Blocked",
            "(none)",
            "",
            "## Key Decisions",
            "(none)",
            "",
            "## Resolved Questions",
            ai_statements[-1][:200] if ai_statements else "(none)",
            "",
            "## Pending User Asks",
            user_texts[-1] if user_texts else "(none)",
            "",
            "## Relevant Files / Remaining Work",
            "(none)",
        ])

        return "\n".join(lines)

    def reset(self) -> None:
        self._cached_summary = ""


# ---------------------------------------------------------------------------
# Phase 4: Message Sanitizer
# ---------------------------------------------------------------------------


class MessageSanitizer:
    """Fix orphan tool_call/result pairs and reassemble final message list."""

    def sanitize(
        self,
        head: list[BaseMessage],
        summary: str,
        tail: list[BaseMessage],
    ) -> list[BaseMessage]:
        """
        Reassemble: head + summary + sanitized-tail.

        Removes orphan messages that would confuse the model.
        """
        # Clean orphan messages from tail
        tail = self._remove_orphans(tail)

        # Build result
        result = list(head)

        if summary:
            result.append(SystemMessage(content=summary))

        result.extend(tail)

        return result

    def _remove_orphans(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """
        Remove ToolMessages without matching AIMessage tool_calls,
        and remove tool_calls from AIMessages whose results are missing.
        """
        # Collect all tool_call_ids present
        all_tc_ids: set[str] = set()
        for msg in messages:
            for tc in getattr(msg, "tool_calls", []) or []:
                tc_id = tc.get("id", "")
                if tc_id:
                    all_tc_ids.add(tc_id)

        # Collect tool_call_ids referenced by ToolMessages
        result_ids: set[str] = set()
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tc_id = getattr(msg, "tool_call_id", "") or ""
                if tc_id:
                    result_ids.add(tc_id)

        cleaned: list[BaseMessage] = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tc_id = getattr(msg, "tool_call_id", "") or ""
                if tc_id not in all_tc_ids:
                    continue  # orphan — skip
                cleaned.append(msg)
            elif isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                # Keep only tool_calls that have matching results
                valid_tcs = [
                    tc for tc in msg.tool_calls
                    if tc.get("id", "") in result_ids
                ]
                if valid_tcs or getattr(msg, "content", ""):
                    cleaned.append(AIMessage(
                        content=getattr(msg, "content", ""),
                        tool_calls=valid_tcs if valid_tcs else None,
                    ))
                # If no valid tcs and no content, skip this message entirely
            else:
                cleaned.append(msg)

        return cleaned

    @staticmethod
    def _find_latest_user_msg(messages: list[BaseMessage]) -> int:
        """Find index of the last HumanMessage."""
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                return i
        return -1


# ---------------------------------------------------------------------------
# Anti-Thrash Tracker
# ---------------------------------------------------------------------------


class AntiThrashTracker:
    """Prevent repeated ineffective compressions."""

    def __init__(self, min_savings: float = 0.1, consecutive_limit: int = 2):
        self.min_savings = min_savings
        self.consecutive_limit = consecutive_limit
        self._consecutive_low: int = 0

    def record_compression(self, savings_ratio: float) -> bool:
        """
        Record a compression event.
        Returns True if thrashing is detected (compression is not helping).
        """
        if savings_ratio < self.min_savings:
            self._consecutive_low += 1
        else:
            self._consecutive_low = 0

        return self._consecutive_low >= self.consecutive_limit

    @property
    def is_thrashing(self) -> bool:
        return self._consecutive_low >= self.consecutive_limit

    def reset(self) -> None:
        self._consecutive_low = 0


# ---------------------------------------------------------------------------
# Orchestrator: Context Compressor Service
# ---------------------------------------------------------------------------


class ContextCompressorService:
    """
    Four-phase context compression engine.

    Usage:
        service = ContextCompressorService(config)
        result = service.compress_messages(messages)
        if result.was_compressed:
            messages = result.messages  # use compressed list
    """

    def __init__(
        self,
        config: CompressorConfig | None = None,
        llm_factory=None,
    ):
        self.config = config or CompressorConfig()
        self.pruner = ToolOutputPruner()
        self.boundary = BoundaryFinder()
        self.summarizer = SummaryGenerator(llm_factory=llm_factory)
        self.sanitizer = MessageSanitizer()
        self.thrash = AntiThrashTracker(
            min_savings=self.config.anti_thrash_min_savings,
            consecutive_limit=self.config.anti_thrash_consecutive_limit,
        )

    def compress_messages(
        self,
        messages: list[BaseMessage],
    ) -> CompressionResult:
        """
        Run the full compression pipeline on a message list.

        Returns CompressionResult with the (possibly compressed) message list.
        """
        if not messages:
            return CompressionResult(
                messages=[],
                was_compressed=False,
                savings_ratio=0.0,
            )

        original_tokens = _total_tokens(messages)

        # Gate: only compress if over threshold
        if original_tokens < self.config.trigger_tokens:
            return CompressionResult(
                messages=list(messages),
                was_compressed=False,
                savings_ratio=0.0,
            )

        # Phase 1: Prune old tool outputs
        pruned = self.pruner.prune(messages, current_turn_start_idx=0)

        # Phase 2: Determine boundaries
        boundaries = self.boundary.find_boundaries(pruned, self.config)

        # If no middle zone, nothing to summarize — just return pruned messages
        if not boundaries.middle:
            compressed = list(pruned)
            compressed_tokens = _total_tokens(compressed)
            savings = 1.0 - (compressed_tokens / original_tokens) if original_tokens > 0 else 0.0
            thrash = self.thrash.record_compression(savings)
            return CompressionResult(
                messages=compressed,
                was_compressed=True,
                savings_ratio=savings,
                thrash_warning=thrash,
            )

        # Phase 3: Summarize the middle zone
        summary_text = self.summarizer.generate(
            boundaries.middle,
            self.config,
        )

        # Phase 4: Reassemble
        final_messages = self.sanitizer.sanitize(
            boundaries.head,
            summary_text,
            boundaries.tail,
        )

        compressed_tokens = _total_tokens(final_messages)
        savings = 1.0 - (compressed_tokens / original_tokens) if original_tokens > 0 else 0.0
        thrash = self.thrash.record_compression(savings)

        return CompressionResult(
            messages=final_messages,
            was_compressed=True,
            savings_ratio=savings,
            thrash_warning=thrash,
            summary_text=summary_text,
        )

    def reset(self) -> None:
        """Clear summaries and thrash counters (e.g., on /new)."""
        self.summarizer.reset()
        self.thrash.reset()
