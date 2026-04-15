from fastapi import HTTPException
from langchain.tools import tool
import requests
from settings.config import config
from loguru import logger
@tool(
    name_or_callable="web_search",
    description="当需要进行网络搜索时，调用该工具，传入参数包括：query（搜索关键词），freshness（搜索结果的新鲜度，可以是noLimit,day,hour等），summary（是否需要对搜索结果进行总结），include（需要包含的关键词），exclude（需要排除的关键词），count（返回的搜索结果数量）"
)
def web_search(query,freshness="noLimit",summary=True,include="",exclude="",count=10):
    try:
        header={
            "Content-Type":"application/json",
            "Authorization":f"Bearer {config.WEB_SEARCH_KEY}"
        }
        pyload={
            "query":query,
            "freshness":freshness,
            "summary":summary,
            "include":include,
            "exclude":exclude,
            "count":count,
            "timeout":60
        }
        response = requests.post(config.WEB_SEARCH_URL, headers=header, json=pyload)
        print(response.json())
        return response.json()
    except Exception as e:
        logger.error(f"联网搜索工具调用失败: {e}")
        return {"error": f"联网搜索失败: {str(e)}"}
    