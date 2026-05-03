"""时间工具 - 获取当前时间信息"""

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from loguru import logger

from .tool_result import ToolResult


@tool(
    name_or_callable="get_current_time",
    description='''
    获取当前时间

    当用户询问"现在几点"、"今天星期几"、"今天日期"等时间相关问题时，使用此工具。

    Args:
        timezone: 时区，默认为 Asia/Shanghai（北京时间）

    Returns:
        str: 格式化的当前时间信息
    '''
)
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        return ToolResult.success(data=now.strftime('%Y-%m-%d %H:%M:%S')).to_message_content()
    except Exception as e:
        logger.error(f"时间查询工具调用失败: {e}")
        return ToolResult.failure(str(e), "TOOL_FAILED").to_message_content()
