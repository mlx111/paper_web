from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mcp_server_registers_three_public_tools():
    text = (ROOT / "app" / "mcp_server.py").read_text(encoding="utf-8")

    assert "FastMCP" in text
    assert 'FastMCP("mypaperweb-tools")' in text
    assert "def mypaper_retrieve_knowledge" in text
    assert "def mypaper_web_search" in text
    assert "def mypaper_get_current_time" in text


def test_mcp_server_reuses_adapter_instead_of_calling_tools_directly():
    text = (ROOT / "app" / "mcp_server.py").read_text(encoding="utf-8")

    assert "from mcp_tools import call_mcp_tool" in text
    assert 'call_mcp_tool("mypaper_retrieve_knowledge"' in text
    assert 'call_mcp_tool("mypaper_web_search"' in text
    assert 'call_mcp_tool("mypaper_get_current_time"' in text
    assert "from tools" not in text
    assert "import tools" not in text
    assert "retrieve_knowledge(" not in text.replace("mypaper_retrieve_knowledge(", "")
    assert "web_search(" not in text.replace("mypaper_web_search(", "")
    assert "get_current_time(" not in text.replace("mypaper_get_current_time(", "")
