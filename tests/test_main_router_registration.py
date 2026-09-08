from pathlib import Path


def test_main_registers_trace_router():
    main_py = Path(__file__).resolve().parents[1] / "app" / "main.py"
    source = main_py.read_text(encoding="utf-8")

    assert "from routers.trace import router as trace_router" in source
    assert "app.include_router(trace_router)" in source
