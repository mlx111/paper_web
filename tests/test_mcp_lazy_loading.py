from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mcp_wrapper_uses_single_tool_registry_factory():
    text = (ROOT / "app" / "mcp_tools.py").read_text(encoding="utf-8")

    assert "def _get_wrapper(internal_tool_name" in text
    assert "build_tool_registry([internal_tool_name])" in text
    assert "from tools import ToolWrapper, tool_registry" not in text


def test_tools_package_no_longer_eager_imports_heavy_tools():
    text = (ROOT / "app" / "tools" / "__init__.py").read_text(encoding="utf-8")

    assert "from .rag_tool import" not in text
    assert "from .academic_tool import" not in text
    assert "from .paper_refiner_tool import" not in text
    assert "from .document_parser_tool import" not in text
    assert "def __getattr__" in text


def test_registry_factory_declares_lazy_tool_imports():
    text = (ROOT / "app" / "tools" / "registry_factory.py").read_text(encoding="utf-8")

    assert '"get_current_time":' in text
    assert '"web_search":' in text
    assert '"retrieve_knowledge":' in text
    assert '"tools.time_tool"' in text
    assert '"tools.websearch_tool"' in text
    assert '"tools.rag_tool"' in text
