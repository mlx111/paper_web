import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import mcp_tools


class FakeResult:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return dict(self.payload)


class FakeWrapper:
    def execute(self, tool_name, args):
        dirty_snippet = """
        [Open in app](https://example.com/app) [Sign in](https://example.com/login)
        ![Image 1](https://example.com/image.png)
        # Querying Literary Agents Made Easy. This is useful content about agent search and evaluation.
        [Privacy](https://example.com/privacy) [Terms](https://example.com/terms)
        """ * 8
        return FakeResult({
            "ok": True,
            "data": {
                "results": [
                    {
                        "title": "Querying Literary Agents Made Easy",
                        "url": "https://example.com/post",
                        "snippet": dirty_snippet,
                        "source": "web",
                        "extra": "drop me",
                    }
                ],
                "_provider": "tavily",
            },
            "summary": "old noisy summary",
            "error": "",
            "error_code": "",
            "truncated": False,
            "truncated_from": 0,
        })


def test_web_search_result_is_sanitized_for_mcp(monkeypatch):
    monkeypatch.setattr(mcp_tools, "_get_wrapper", lambda internal_name: FakeWrapper())

    payload = mcp_tools.call_mcp_tool("mypaper_web_search", {"query": "agent", "count": 1})

    result = payload["data"]["results"][0]
    snippet = result["snippet"]
    assert payload["ok"] is True
    assert payload["data"]["_provider"] == "tavily"
    assert set(result) == {"title", "url", "snippet", "source"}
    assert len(snippet) <= 320
    assert "![" not in snippet
    assert "](" not in snippet
    assert "Open in app" not in snippet
    assert "Sign in" not in snippet
    assert "Privacy" not in snippet
    assert "Terms" not in snippet
    assert payload["summary"] == "Found 1 web search result, provider=tavily"
