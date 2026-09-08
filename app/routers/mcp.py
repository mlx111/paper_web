"""MCP Host 可观测接口：查看外部 MCP server 连接状态与动态注册的工具清单。"""

from __future__ import annotations

from fastapi import APIRouter

from services.mcp_client_service import mcp_client_service

router = APIRouter(prefix="/api/mcp", tags=["mcp-host"])


@router.get("/servers")
def mcp_servers():
    """外部 MCP server 连接状态（名称 / transport / 发现工具数 / 错误）。"""
    return {"servers": mcp_client_service.get_servers()}


@router.get("/tools")
def mcp_tools():
    """MCP Host 动态注册的外部工具清单（source 恒为 mcp）。

    返回每项含 server、tool、qualified_name、description、transport，
    供前端工具面板区分工具来源（本地 local / Skill / 外部 MCP）。
    """
    return {"tools": mcp_client_service.get_inventory(), "count": len(mcp_client_service.get_inventory())}
