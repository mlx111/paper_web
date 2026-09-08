"""
MCP Host：在运行时发现并动态注册外部 MCP server 的工具。

能力：
- 读取 ``app/mcp_servers.json`` 配置，支持两种 transport：
  - ``stdio``：把 MCP server 作为子进程拉起（命令 + 参数）；
  - ``http`` / ``streamable-http``：连接远程 streamable-http MCP server。
- 启动时连接每个启用的 server，``list_tools()`` 发现工具；
- 把每个 MCP 工具按其 JSON Schema 动态包装成 LangChain ``StructuredTool``，
  统一命名为 ``mcp__<server>__<tool>``，Agent 可像调用本地工具一样直接调用；
- 工具来源标记为 ``source="mcp"``，与本地工具(local)/Skill 区分，供工具面板/
  链路追踪展示「工具来源 = 本地 + Skills + 外部 MCP」。

连接在 FastAPI lifespan 中建立并长期持有（AsyncExitStack），关闭时统一清理。
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "mcp_servers.json"


def _json_type_to_python(json_type: str | None):
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }.get(json_type or "string", str)


class MCPClientService:
    """单例 MCP Host：管理到多个外部 MCP server 的连接与工具注册。"""

    def __init__(self):
        self._tools: list = []
        self._inventory: list[dict[str, Any]] = []
        self._servers: list[dict[str, Any]] = []
        self._exit_stack: contextlib.AsyncExitStack | None = None
        self._connected = False

    # ── 生命周期 ───────────────────────────────────────────────────
    async def connect_all(self, config_path: str | Path | None = None) -> dict[str, Any]:
        """连接配置中所有启用的 MCP server。幂等；失败不抛、仅记录。"""
        if self._connected:
            return {"servers": self._servers}

        path = Path(config_path or _CONFIG_PATH)
        if not path.exists():
            logger.info("MCP Host: 未找到配置 {}，跳过外部 MCP 工具注册", path)
            self._connected = True
            return {"servers": [], "skipped": "no config file"}

        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.error("MCP Host: 配置解析失败 {}: {}", path, exc)
            self._connected = True
            return {"servers": [], "error": str(exc)}

        self._exit_stack = contextlib.AsyncExitStack()
        await self._exit_stack.__aenter__()

        for spec in config.get("servers", []):
            if not spec.get("enabled", False):
                logger.info("MCP Host: server '{}' 未启用，跳过", spec.get("name"))
                continue
            try:
                info = await self._connect_one(spec, path.parent)
                self._servers.append(info)
                logger.info(
                    "MCP Host: 已连接 '{}'（{}），发现 {} 个工具: {}",
                    info["name"], info["transport"], info["tool_count"], info["tools"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("MCP Host: 连接 server '{}' 失败: {}", spec.get("name"), exc)
                self._servers.append({"name": spec.get("name"), "transport": spec.get("transport"), "error": str(exc)})

        self._connected = True
        logger.info("MCP Host: 初始化完成，共注册 {} 个外部 MCP 工具", len(self._tools))
        return {"servers": self._servers}

    async def close(self) -> None:
        if self._exit_stack is not None:
            with contextlib.suppress(Exception):
                await self._exit_stack.aclose()
        self._exit_stack = None
        self._connected = False
        logger.info("MCP Host: 已关闭所有外部 MCP 连接")

    async def _connect_one(self, spec: dict[str, Any], config_dir: Path) -> dict[str, Any]:
        name = spec["name"]
        transport = (spec.get("transport") or "stdio").lower()

        if transport == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            command, args = self._resolve_stdio(spec, config_dir)
            params = StdioServerParameters(
                command=command,
                args=args,
                env={**os.environ, **(spec.get("env") or {})},
            )
            read, write = await self._exit_stack.enter_async_context(stdio_client(params))

        elif transport in ("http", "streamable-http", "streamable_http"):
            from mcp.client.streamable_http import streamablehttp_client

            read, write, _ = await self._exit_stack.enter_async_context(
                streamablehttp_client(spec["url"])
            )
        else:
            raise ValueError(f"不支持的 transport: {transport}")

        from mcp import ClientSession

        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        result = await session.list_tools()
        tools = result.tools or []
        lc_tools, inventory = self._wrap_tools(name, transport, session, tools)
        self._tools.extend(lc_tools)
        self._inventory.extend(inventory)

        return {
            "name": name,
            "transport": transport,
            "tool_count": len(tools),
            "tools": [item["tool"] for item in inventory],
        }

    # ── 工具包装 ───────────────────────────────────────────────────
    def _wrap_tools(self, server_name: str, transport: str, session, tools: list):
        from langchain_core.tools import StructuredTool

        lc_tools: list = []
        inventory: list[dict[str, Any]] = []

        for mcp_tool in tools:
            qualified = f"mcp__{server_name}__{mcp_tool.name}"
            args_schema = self._build_args_schema(qualified, mcp_tool.input_schema or {})
            description = f"[MCP:{server_name}] {mcp_tool.description or mcp_tool.name}"

            def _make_coro(raw_name: str = mcp_tool.name, sess=session):
                async def _coroutine(**kwargs):
                    result = await sess.call_tool(raw_name, kwargs or None)
                    return self._extract_text(result)

                return _coroutine

            lc_tools.append(
                StructuredTool(
                    name=qualified,
                    description=description,
                    args_schema=args_schema,
                    coroutine=_make_coro(),
                )
            )
            inventory.append(
                {
                    "server": server_name,
                    "tool": mcp_tool.name,
                    "qualified_name": qualified,
                    "description": mcp_tool.description or "",
                    "source": "mcp",
                    "transport": transport,
                }
            )

        return lc_tools, inventory

    @staticmethod
    def _build_args_schema(qualified_name: str, input_schema: dict[str, Any]):
        from pydantic import Field, create_model

        properties = (input_schema or {}).get("properties", {}) or {}
        required = set((input_schema or {}).get("required", []) or [])

        fields: dict[str, Any] = {}
        for arg_name, arg_spec in properties.items():
            py_type = _json_type_to_python(arg_spec.get("type"))
            desc = arg_spec.get("description", "")
            if arg_name in required:
                fields[arg_name] = (py_type, Field(..., description=desc))
            else:
                fields[arg_name] = (py_type, Field(default=None, description=desc))

        model_name = qualified_name.replace("__", "_") + "_args"
        return create_model(model_name, **fields)

    @staticmethod
    def _extract_text(result: Any) -> str:
        parts: list[str] = []
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts)
        return str(result)

    # ── 工具查询 ───────────────────────────────────────────────────
    def get_langchain_tools(self) -> list:
        """返回可直接绑定给 Agent 的 LangChain 工具对象列表。"""
        return list(self._tools)

    def get_inventory(self) -> list[dict[str, Any]]:
        """返回带来源标记的工具清单（供工具面板/可观测 API）。"""
        return list(self._inventory)

    def get_servers(self) -> list[dict[str, Any]]:
        return list(self._servers)

    # ── helpers ────────────────────────────────────────────────────
    @staticmethod
    def _resolve_stdio(spec: dict[str, Any], config_dir: Path) -> tuple[str, list[str]]:
        command = spec.get("command") or "python"
        if command in ("python", "python3"):
            command = sys.executable  # 用当前解释器，容器/本地都稳

        resolved_args: list[str] = []
        for arg in spec.get("args", []) or []:
            if isinstance(arg, str) and arg.endswith(".py") and not os.path.isabs(arg):
                candidate = config_dir / arg
                if candidate.exists():
                    arg = str(candidate)
            resolved_args.append(arg)
        return command, resolved_args


# 单例
mcp_client_service = MCPClientService()
