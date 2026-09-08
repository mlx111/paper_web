from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_app(path: str) -> str:
    return (ROOT / "app" / path).read_text(encoding="utf-8")


def test_agent_stream_router_forwards_context_event():
    source = read_app("routers/agent.py")

    assert 'chunk_type == "context"' in source
    assert '"type": "context"' in source


def test_file_stream_router_forwards_context_event():
    source = read_app("routers/file.py")

    assert 'chunk_type == "context"' in source
    assert '"type": "context"' in source
