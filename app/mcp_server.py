from __future__ import annotations

from typing import Any

from mcp_tools import call_mcp_tool

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    class FastMCP:
        def __init__(self, name: str):
            self.name = name

        def tool(self, *args: Any, **kwargs: Any):
            def decorator(func):
                return func

            return decorator

        def run(self) -> None:
            raise RuntimeError("The 'mcp' package is not installed. Run pip install -r requirements.txt first.")


mcp = FastMCP("mypaperweb-tools")


@mcp.tool()
def mypaper_retrieve_knowledge(query: str) -> dict[str, Any]:
    """Search the local mypaperweb knowledge base."""
    return call_mcp_tool("mypaper_retrieve_knowledge", {"query": query})


@mcp.tool()
def mypaper_web_search(query: str, count: int = 5) -> dict[str, Any]:
    """Search the web through the existing mypaperweb web_search tool."""
    return call_mcp_tool("mypaper_web_search", {"query": query, "count": count})


@mcp.tool()
def mypaper_get_current_time(timezone: str = "Asia/Shanghai") -> dict[str, Any]:
    """Get the current time for a timezone."""
    return call_mcp_tool("mypaper_get_current_time", {"timezone": timezone})


if __name__ == "__main__":
    mcp.run()
