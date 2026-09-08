"""
容器内置的「外部 MCP server」演示（stdio transport）。

mypaperweb 的 MCP Host（app/services/mcp_client_service.py）在启动时会把本文件
作为独立子进程拉起，通过 MCP 协议 list_tools() / call_tool() 发现并调用这里的
工具。对 Host 而言，它就是一个标准的、进程隔离的外部 MCP server —— 与用 Node、
Go 或其他远程服务实现的 MCP server 没有区别。

生产环境可把配置（app/mcp_servers.json）指向任意第三方 MCP server
（stdio 或 streamable-http），无需改动 Host 代码。

运行方式（手动调试）：
    python app/mcp_external_demo_server.py     # 通过 stdio 提供 MCP 服务
"""

from __future__ import annotations

import ast
import operator
from typing import Any

try:
    # mcp>=2.0：FastMCP 更名为 MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP
except (ModuleNotFoundError, ImportError):  # pragma: no cover
    try:
        from mcp.server.fastmcp import FastMCP  # mcp<2.0
    except ModuleNotFoundError:  # pragma: no cover
        raise SystemExit("未安装 mcp 包，无法启动 demo MCP server：pip install mcp")

mcp = FastMCP("demo-external-tools")


# ── 安全数学表达式求值（白名单 AST，不用 eval） ──────────────────────
_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_safe_eval(node.operand))
    raise ValueError("仅支持数字与 + - * / ** % // 运算")


@mcp.tool()
def calculator(expression: str) -> dict[str, Any]:
    """安全计算一个数学表达式，支持加减乘除、幂、取模、整除与括号，例如 "(3+4)*2" 或 "2**10"。"""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _safe_eval(tree.body)
        return {"ok": True, "expression": expression, "result": result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "expression": expression, "error": str(exc)}


@mcp.tool()
def text_stats(text: str) -> dict[str, Any]:
    """统计给定文本的字符数、按空白切分的单词数、中文汉字数与行数。"""
    chars = len(text)
    words = len(text.split())
    han_chars = sum(1 for ch in text if "一" <= ch <= "鿿")
    lines = len(text.splitlines()) or (1 if text else 0)
    return {"ok": True, "chars": chars, "words": words, "han_chars": han_chars, "lines": lines}


if __name__ == "__main__":
    mcp.run()
