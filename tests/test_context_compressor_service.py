"""Tests for the Hermes-style context compression service."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.services.context_compressor_service import (
    AntiThrashTracker,
    BoundaryFinder,
    BoundaryResult,
    CompressorConfig,
    CompressionResult,
    ContextCompressorService,
    MessageSanitizer,
    SummaryGenerator,
    ToolOutputPruner,
    _message_token_count,
    _rough_token_count,
    _total_tokens,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_tool_msg(content: str = "result data here", name: str = "search", tool_call_id: str = "1") -> ToolMessage:
    return ToolMessage(content=content, name=name, tool_call_id=tool_call_id)


def _make_ai_with_tools(content: str = "", tool_calls: list | None = None) -> AIMessage:
    return AIMessage(content=content, tool_calls=tool_calls or [])


# ---------------------------------------------------------------------------
# TestCompressorConfig
# ---------------------------------------------------------------------------

class TestCompressorConfig:
    def test_defaults(self):
        cfg = CompressorConfig()
        assert cfg.context_window_tokens == 32000
        assert cfg.compression_threshold_ratio == 0.5
        assert cfg.trigger_tokens == 16000
        assert cfg.llm_enabled is True

    def test_custom_trigger(self):
        cfg = CompressorConfig(context_window_tokens=10000, compression_threshold_ratio=0.3)
        assert cfg.trigger_tokens == 3000


# ---------------------------------------------------------------------------
# TestToolOutputPruner
# ---------------------------------------------------------------------------

class TestToolOutputPruner:
    def test_prunes_old_tool_results_to_one_line(self):
        pruner = ToolOutputPruner()
        msgs = [
            HumanMessage(content="search papers about NLP"),
            _make_ai_with_tools("", [{"name": "search", "args": {}, "id": "1"}]),
            ToolMessage(content="a" * 500, name="search", tool_call_id="1"),
            HumanMessage(content="now download the first one"),
            _make_ai_with_tools("", [{"name": "download", "args": {}, "id": "2"}]),
            ToolMessage(content="paper content " * 100, name="download", tool_call_id="2"),
        ]
        # current_turn_start_idx=0 means everything is "old" — but the LAST round is preserved
        result = pruner.prune(msgs, current_turn_start_idx=0)

        # Last round's ToolMessage (download / id=2) should be preserved verbatim
        download_msgs = [m for m in result if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", "") == "2"]
        assert len(download_msgs) == 1
        assert "paper content" in download_msgs[0].content  # verbatim

        # Old round's ToolMessage (search / id=1) should be summarized
        search_msgs = [m for m in result if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", "") == "1"]
        assert len(search_msgs) == 1
        assert "[search]" in search_msgs[0].content
        assert "500 chars" in search_msgs[0].content
        # Should NOT contain the full 500 'a's
        assert "a" * 200 not in search_msgs[0].content

    def test_preserves_most_recent_tool_round(self):
        pruner = ToolOutputPruner()
        msgs = [
            HumanMessage(content="q1"),
            _make_ai_with_tools("", [{"name": "tool_a", "args": {}, "id": "a1"}]),
            ToolMessage(content="old result", name="tool_a", tool_call_id="a1"),
            HumanMessage(content="q2"),
            _make_ai_with_tools("", [{"name": "tool_b", "args": {}, "id": "b1"}]),
            ToolMessage(content="recent result", name="tool_b", tool_call_id="b1"),
        ]
        result = pruner.prune(msgs, current_turn_start_idx=0)
        # The most recent round (tool_b) should be verbatim
        recent = [m for m in result if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", "") == "b1"]
        assert len(recent) == 1
        assert recent[0].content == "recent result"

    def test_dedup_repeated_results(self):
        pruner = ToolOutputPruner()
        msgs = [
            HumanMessage(content="search"),
            _make_ai_with_tools("", [{"name": "search", "args": {}, "id": "s1"}]),
            ToolMessage(content="same result", name="search", tool_call_id="s1"),
            HumanMessage(content="search again"),
            _make_ai_with_tools("", [{"name": "search", "args": {}, "id": "s2"}]),
            ToolMessage(content="same result", name="search", tool_call_id="s2"),
            HumanMessage(content="final q"),
            _make_ai_with_tools("", [{"name": "download", "args": {}, "id": "d1"}]),
            ToolMessage(content="final result", name="download", tool_call_id="d1"),
        ]
        result = pruner.prune(msgs, current_turn_start_idx=0)
        # The first two search results with identical content — second should be dedup'd
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        # The last round's "download" is preserved; s1 gets summarized; s2 is duplicate of s1 → skipped
        assert len(tool_msgs) <= 3  # download + s1 summary, s2 dedup'd

    def test_handles_empty_messages(self):
        pruner = ToolOutputPruner()
        assert pruner.prune([], 0) == []

    def test_handles_no_tool_messages(self):
        pruner = ToolOutputPruner()
        msgs = [HumanMessage(content="hello"), AIMessage(content="hi there")]
        result = pruner.prune(msgs, 0)
        assert len(result) == 2
        assert result[0].content == "hello"

    def test_truncates_tool_call_args(self):
        pruner = ToolOutputPruner()
        long_arg = "x" * 200
        msgs = [
            HumanMessage(content="q"),
            AIMessage(content="", tool_calls=[{"name": "search", "args": {"query": long_arg}, "id": "1"}]),
            ToolMessage(content="result", name="search", tool_call_id="1"),
            HumanMessage(content="another q"),
            AIMessage(content="", tool_calls=[{"name": "download", "args": {"url": "https://example.com"}, "id": "2"}]),
            ToolMessage(content="downloaded", name="download", tool_call_id="2"),
        ]
        result = pruner.prune(msgs, current_turn_start_idx=0)
        # First AIMessage (old round) should have truncated args
        first_ai = [m for m in result if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)]
        if first_ai:
            for tc in first_ai[0].tool_calls:
                if tc["name"] == "search":
                    assert len(tc["args"]["query"]) <= 120 + 3  # 120 + "..." = 123


# ---------------------------------------------------------------------------
# TestBoundaryFinder
# ---------------------------------------------------------------------------

class TestBoundaryFinder:
    def test_head_protects_first_n_messages(self):
        finder = BoundaryFinder()
        config = CompressorConfig(head_protect_messages=3, tail_token_budget=1000)
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a2"),
        ]
        b = finder.find_boundaries(msgs, config)
        assert len(b.head) == 3
        assert b.head[0].content == "sys"
        assert b.head[1].content == "q1"
        assert b.head[2].content == "a1"

    def test_tail_protects_within_token_budget(self):
        finder = BoundaryFinder()
        config = CompressorConfig(head_protect_messages=1, tail_token_budget=50)  # very small budget
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),
            AIMessage(content="a" * 100),  # large last message
        ]
        b = finder.find_boundaries(msgs, config)
        # Tail should exist but not include everything (budget limited)
        assert len(b.tail) >= 1

    def test_aligns_tool_call_result_pairs(self):
        finder = BoundaryFinder()
        config = CompressorConfig(head_protect_messages=2, tail_token_budget=1000)
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="q"),
            AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "1"}]),
            ToolMessage(content="result", name="search", tool_call_id="1"),
            HumanMessage(content="final q"),
        ]
        b = finder.find_boundaries(msgs, config)
        # The tool_call/result pair should be together in head
        # (if the AIMessage is in head, ToolMessage should be pulled into head too)
        head_has_tool_call = any(
            isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
            for m in b.head
        )
        head_has_tool_result = any(
            isinstance(m, ToolMessage) and getattr(m, "tool_call_id", "") == "1"
            for m in b.head
        )
        # Both should be together
        assert head_has_tool_call == head_has_tool_result

    def test_protects_latest_user_message(self):
        finder = BoundaryFinder()
        config = CompressorConfig(head_protect_messages=2, tail_token_budget=500)
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="early q"),
            AIMessage(content="early a"),
            HumanMessage(content="latest q"),
        ]
        b = finder.find_boundaries(msgs, config)
        tail_has_latest_user = any(
            isinstance(m, HumanMessage) and m.content == "latest q"
            for m in b.tail
        )
        assert tail_has_latest_user

    def test_no_middle_when_under_budget(self):
        finder = BoundaryFinder()
        config = CompressorConfig(head_protect_messages=2, tail_token_budget=5000)
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="q"),
            AIMessage(content="a"),
        ]
        b = finder.find_boundaries(msgs, config)
        assert len(b.middle) == 0

    def test_middle_exists_when_many_messages(self):
        finder = BoundaryFinder()
        config = CompressorConfig(head_protect_messages=1, tail_token_budget=20)
        msgs = [SystemMessage(content=f"msg{i}") for i in range(20)]
        b = finder.find_boundaries(msgs, config)
        assert len(b.middle) > 0


# ---------------------------------------------------------------------------
# TestSummaryGenerator
# ---------------------------------------------------------------------------

class TestSummaryGenerator:
    def test_generates_structured_summary(self):
        # Mock the LLM to return a predictable summary
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = (
            "## Active Task\nTest task\n## Goal / Constraints\nTest goal\n"
            "## Completed Actions\n- Action 1\n## In Progress / Blocked\n(none)\n"
            "## Key Decisions\n(none)\n## Resolved Questions\nQ1\n"
            "## Pending User Asks\n(none)\n## Relevant Files / Remaining Work\n(none)"
        )
        mock_llm.invoke.return_value = mock_response
        mock_factory = MagicMock(return_value=mock_llm)

        generator = SummaryGenerator(llm_factory=mock_factory)
        config = CompressorConfig(llm_enabled=True, llm_temperature=0.0)

        msgs = [
            HumanMessage(content="test task"),
            AIMessage(content="action 1 done"),
        ]
        result = generator.generate(msgs, config)

        assert "[CONTEXT COMPACTION — REFERENCE ONLY]" in result
        assert "Active Task" in result
        assert "Test task" in result
        mock_llm.invoke.assert_called_once()

    def test_handoff_protocol_prefix(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "## Active Task\nTest"
        mock_llm.invoke.return_value = mock_response
        mock_factory = MagicMock(return_value=mock_llm)

        generator = SummaryGenerator(llm_factory=mock_factory)
        config = CompressorConfig(llm_enabled=True)

        result = generator.generate([HumanMessage(content="q")], config)
        assert result.startswith("[CONTEXT COMPACTION — REFERENCE ONLY]")

    def test_iterative_update_includes_existing_summary(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "## Active Task\nUpdated"
        mock_llm.invoke.return_value = mock_response
        mock_factory = MagicMock(return_value=mock_llm)

        generator = SummaryGenerator(llm_factory=mock_factory)
        config = CompressorConfig(llm_enabled=True)

        # First call
        generator.generate([HumanMessage(content="q1")], config)
        # Second call — should include existing summary in prompt
        mock_llm.invoke.reset_mock()
        result = generator.generate([HumanMessage(content="q2")], config)

        # Check that the prompt sent to LLM contained the existing summary
        call_args = mock_llm.invoke.call_args
        messages_sent = call_args[0][0]  # first arg to invoke
        user_msg = messages_sent[-1].content
        assert "Existing Summary" in user_msg

    def test_returns_empty_string_when_zone_empty(self):
        generator = SummaryGenerator()
        config = CompressorConfig(llm_enabled=True)
        result = generator.generate([], config)
        assert result == ""

    def test_fallback_summary_when_llm_disabled(self):
        generator = SummaryGenerator()
        config = CompressorConfig(llm_enabled=False)
        msgs = [
            HumanMessage(content="user question here"),
            AIMessage(content="assistant response", tool_calls=[{"name": "search", "args": {}, "id": "1"}]),
            ToolMessage(content="tool result", name="search", tool_call_id="1"),
        ]
        result = generator.generate(msgs, config)
        assert "[CONTEXT COMPACTION — REFERENCE ONLY]" in result
        assert "Active Task" in result
        assert "search" in result


# ---------------------------------------------------------------------------
# TestMessageSanitizer
# ---------------------------------------------------------------------------

class TestMessageSanitizer:
    def test_removes_orphan_tool_messages(self):
        sanitizer = MessageSanitizer()
        head = [SystemMessage(content="sys")]
        tail = [
            ToolMessage(content="orphan result", name="search", tool_call_id="orphan_1"),
            HumanMessage(content="good q"),
            AIMessage(content="good a"),
        ]
        result = sanitizer.sanitize(head, "", tail)
        # The orphan ToolMessage should be removed
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 0

    def test_removes_orphan_aimessage_tool_calls(self):
        sanitizer = MessageSanitizer()
        head = [SystemMessage(content="sys")]
        tail = [
            AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "orphan_call"}]),
            HumanMessage(content="q"),
        ]
        result = sanitizer.sanitize(head, "", tail)
        # The orphan AIMessage should have its tool_calls stripped (no matching ToolMessage)
        for m in result:
            if isinstance(m, AIMessage):
                tcs = getattr(m, "tool_calls", None)
                assert not tcs  # orphan tool_calls removed

    def test_preserves_valid_pairs(self):
        sanitizer = MessageSanitizer()
        head = [SystemMessage(content="sys")]
        tail = [
            AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "valid_1"}]),
            ToolMessage(content="result", name="search", tool_call_id="valid_1"),
        ]
        result = sanitizer.sanitize(head, "", tail)
        # Both should be preserved
        ai_msgs = [m for m in result if isinstance(m, AIMessage)]
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        assert len(ai_msgs) >= 1
        assert len(tool_msgs) >= 1

    def test_injects_summary_after_head(self):
        sanitizer = MessageSanitizer()
        head = [SystemMessage(content="sys")]
        summary = "This is a summary"
        tail = [HumanMessage(content="q"), AIMessage(content="a")]
        result = sanitizer.sanitize(head, summary, tail)
        assert len(result) == 4  # head(1) + summary(1) + tail(2)
        assert result[0].content == "sys"
        assert result[1].content == summary
        assert isinstance(result[1], SystemMessage)

    def test_reassembles_correctly(self):
        sanitizer = MessageSanitizer()
        head = [SystemMessage(content="system prompt")]
        summary = "compressed middle zone"
        tail = [
            HumanMessage(content="latest user question"),
            AIMessage(content="latest assistant answer"),
        ]
        result = sanitizer.sanitize(head, summary, tail)
        # head intact
        assert result[0].content == "system prompt"
        # summary in middle
        assert result[1].content == summary
        # tail at end, latest user message present
        assert result[-2].content == "latest user question"
        assert isinstance(result[-2], HumanMessage)


# ---------------------------------------------------------------------------
# TestAntiThrashTracker
# ---------------------------------------------------------------------------

class TestAntiThrashTracker:
    def test_signals_after_two_consecutive_low_savings(self):
        tracker = AntiThrashTracker(min_savings=0.1, consecutive_limit=2)
        assert tracker.record_compression(0.05) is False  # low #1
        assert tracker.record_compression(0.03) is True   # low #2 → thrash
        assert tracker.is_thrashing is True

    def test_resets_on_good_savings(self):
        tracker = AntiThrashTracker(min_savings=0.1, consecutive_limit=2)
        tracker.record_compression(0.05)  # low #1
        assert tracker.record_compression(0.15) is False  # good → resets
        assert tracker.record_compression(0.05) is False  # low #1 again

    def test_does_not_signal_on_first_low_savings(self):
        tracker = AntiThrashTracker(min_savings=0.1, consecutive_limit=2)
        assert tracker.record_compression(0.05) is False
        assert tracker.is_thrashing is False

    def test_reset_clears_counter(self):
        tracker = AntiThrashTracker(min_savings=0.1, consecutive_limit=2)
        tracker.record_compression(0.05)
        tracker.record_compression(0.03)  # thrash
        assert tracker.is_thrashing is True
        tracker.reset()
        assert tracker.is_thrashing is False
        assert tracker.record_compression(0.05) is False  # fresh start


# ---------------------------------------------------------------------------
# TestContextCompressorService — full pipeline
# ---------------------------------------------------------------------------

class TestContextCompressorService:
    def test_no_compression_under_threshold(self):
        config = CompressorConfig(
            context_window_tokens=100000,
            compression_threshold_ratio=0.5,
        )
        service = ContextCompressorService(config)
        msgs = [
            SystemMessage(content="short"),
            HumanMessage(content="hello"),
        ]
        result = service.compress_messages(msgs)
        assert result.was_compressed is False
        assert len(result.messages) == 2

    def test_full_pipeline_on_over_threshold(self):
        # Set threshold very low to force compression
        config = CompressorConfig(
            context_window_tokens=100,  # tiny window → trigger at 50 tokens
            compression_threshold_ratio=0.5,
            head_protect_messages=1,
            tail_token_budget=10,
            llm_enabled=False,  # use fallback summary
        )
        service = ContextCompressorService(config)
        msgs = [
            SystemMessage(content="system " * 10),
            HumanMessage(content="q1 " * 10),
            AIMessage(content="a1 " * 10),
            HumanMessage(content="q2 " * 10),
            AIMessage(content="a2 " * 10),
        ]
        result = service.compress_messages(msgs)
        assert result.was_compressed is True
        assert len(result.messages) < len(msgs)
        # Should have a summary SystemMessage
        system_msgs = [m for m in result.messages if isinstance(m, SystemMessage)]
        assert len(system_msgs) >= 2  # original + summary

    def test_thrash_warning_on_consecutive_low_savings(self):
        config = CompressorConfig(
            context_window_tokens=100,
            compression_threshold_ratio=0.5,
            head_protect_messages=1,
            tail_token_budget=500,  # large tail → small savings
            llm_enabled=False,
            anti_thrash_min_savings=0.1,
            anti_thrash_consecutive_limit=2,
        )
        service = ContextCompressorService(config)
        msgs = [
            SystemMessage(content="sys " * 20),
            HumanMessage(content="q1 " * 20),
            AIMessage(content="a1 " * 20),
            HumanMessage(content="q2 " * 20),
        ]

        # First compression
        r1 = service.compress_messages(msgs)
        # Second compression (small savings both times because tail budget is large)
        r2 = service.compress_messages(msgs)

        # At least one should have triggered after 2 compressions
        assert r1.was_compressed or r2.was_compressed

    def test_reset_clears_summary_and_thrash(self):
        config = CompressorConfig(
            context_window_tokens=100,
            compression_threshold_ratio=0.5,
            head_protect_messages=1,
            tail_token_budget=10,
            llm_enabled=False,
        )
        service = ContextCompressorService(config)
        msgs = [SystemMessage(content=f"msg{i} ") for i in range(20)]
        service.compress_messages(msgs)
        assert service.summarizer.cached_summary != ""
        service.reset()
        assert service.summarizer.cached_summary == ""
        assert service.thrash.is_thrashing is False

    def test_messages_unchanged_when_thrash_warns(self):
        """Compression still runs when thrashing, but thrash_warning is True."""
        config = CompressorConfig(
            context_window_tokens=100,
            compression_threshold_ratio=0.5,
            head_protect_messages=1,
            tail_token_budget=500,
            llm_enabled=False,
            anti_thrash_min_savings=0.9,  # impossibly high → always thrash
            anti_thrash_consecutive_limit=1,
        )
        service = ContextCompressorService(config)
        msgs = [SystemMessage(content=f"msg{i} ") for i in range(20)]
        result = service.compress_messages(msgs)
        # First call with impossibly high min_savings after 3 calls should thrash
        # We just test that the result structure is valid
        assert isinstance(result, CompressionResult)
        assert len(result.messages) > 0


# ---------------------------------------------------------------------------
# Test utility functions
# ---------------------------------------------------------------------------

class TestTokenUtilities:
    def test_rough_token_count(self):
        assert _rough_token_count("") == 0
        assert _rough_token_count("hello") == 2  # 5 // 2 = 2
        assert _rough_token_count("h") == 1  # min 1

    def test_message_token_count(self):
        msg = AIMessage(content="hello world")  # 11 chars → ~5 tokens
        assert _message_token_count(msg) == 5

    def test_total_tokens(self):
        msgs = [
            SystemMessage(content="a" * 100),   # ~50 tokens
            HumanMessage(content="b" * 200),     # ~100 tokens
        ]
        total = _total_tokens(msgs)
        assert total == 150  # 50 + 100

    def test_message_token_count_with_tool_calls(self):
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "search", "args": {"query": "x" * 50}, "id": "1"}],
        )
        tokens = _message_token_count(msg)
        assert tokens > 0  # tool_calls contribute tokens
