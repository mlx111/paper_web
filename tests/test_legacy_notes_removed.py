"""The context pipeline must use structured memory without legacy notes."""

import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from context.gatherer import ContextGatherer


def test_gather_uses_structured_memory_only():
    gatherer = ContextGatherer(
        history_loader=lambda _: [],
        memory_loader=lambda query, limit: [
            {"title": "preference", "content": "Use concise answers", "kind": "user"}
        ],
    )

    candidates, history = gatherer.gather("answer style", "session-1", top_k=0)

    assert history == []
    assert [candidate.source for candidate in candidates] == ["memory"]
    assert "Use concise answers" in candidates[0].content
    assert not hasattr(gatherer, "notes_loader")
