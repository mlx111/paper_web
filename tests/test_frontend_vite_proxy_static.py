from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vite_proxy_includes_evaluation_api():
    config = (ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")

    assert '"/evaluation"' in config
    assert 'target: "http://127.0.0.1:8080"' in config
