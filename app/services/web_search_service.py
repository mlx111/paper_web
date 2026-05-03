"""Multi-provider web search with automatic fallback.

Usage:
    service = WebSearchService()
    result = service.search("量子计算", count=5)
    # Returns normalized {"results": [...], "_provider": "tavily"}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import requests
from loguru import logger
from tavily import TavilyClient

from settings.config import config


class SearchProvider(ABC):
    """Abstract search provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier, e.g. 'tavily'."""

    @abstractmethod
    def search(self, query: str, count: int = 10) -> dict[str, Any]:
        """Execute a web search. Returns normalized dict with 'results' key."""


class TavilyProvider(SearchProvider):
    """Tavily search (preferred)."""

    @property
    def name(self) -> str:
        return "tavily"

    def search(self, query: str, count: int = 10) -> dict[str, Any]:
        client = TavilyClient(api_key=config.TAVILY_API_KEY)
        response = client.search(query=query, max_results=count)
        raw_results = response.get("results") or []
        return {
            "results": [
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", ""),
                    "source": item.get("source", "web"),
                }
                for item in raw_results
                if isinstance(item, dict)
            ],
        }


class BochaProvider(SearchProvider):
    """Bocha.cn search (fallback)."""

    @property
    def name(self) -> str:
        return "bocha"

    def search(self, query: str, count: int = 10) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.WEB_SEARCH_KEY}",
        }
        payload: dict[str, Any] = {
            "query": query,
            "count": count,
            "timeout": 60,
        }
        response = requests.post(
            config.WEB_SEARCH_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )
        data = response.json()
        # Try various key names to find the result list
        raw_items = (
            data.get("data")
            or data.get("results")
            or data.get("items")
            or data.get("documents")
            or []
        )
        return {
            "results": [
                {
                    "title": item.get("title", item.get("name", "")),
                    "url": item.get("url", item.get("link", "")),
                    "snippet": item.get("snippet", item.get("content", item.get("summary", ""))),
                    "source": item.get("source", item.get("site_name", "web")),
                }
                for item in raw_items
                if isinstance(item, dict)
            ],
        }


class WebSearchService:
    """Multi-provider web search with automatic fallback."""

    def __init__(self) -> None:
        self._providers: list[SearchProvider] = []

        if config.TAVILY_API_KEY:
            self._providers.append(TavilyProvider())
        else:
            logger.warning("TAVILY_API_KEY not configured, skipping Tavily provider")

        if config.WEB_SEARCH_KEY and config.WEB_SEARCH_URL:
            self._providers.append(BochaProvider())
        else:
            logger.warning("WEB_SEARCH_KEY/URL not configured, skipping Bocha provider")

    @property
    def available_providers(self) -> list[str]:
        return [p.name for p in self._providers]

    def search(self, query: str, count: int = 10) -> dict[str, Any]:
        """Search using available providers with automatic fallback.

        Returns normalized dict with 'results' key. On total failure,
        returns {"error": "..."}.
        """
        if not self._providers:
            logger.error("No search providers configured")
            return {"error": "没有可用的搜索服务，请配置 TAVILY_API_KEY 或 WEB_SEARCH_KEY"}

        errors: list[str] = []
        for provider in self._providers:
            try:
                logger.info("web_search: trying provider={}", provider.name)
                result = provider.search(query, count)
                result["_provider"] = provider.name
                logger.info(
                    "web_search: provider={} returned {} results",
                    provider.name,
                    len(result.get("results", [])),
                )
                return result
            except Exception as exc:
                logger.warning("web_search: provider={} failed: {}", provider.name, exc)
                errors.append(f"{provider.name}: {exc}")
                continue

        error_msg = f"All search providers failed: {'; '.join(errors)}"
        logger.error(error_msg)
        return {"error": error_msg}


# Singleton for convenience
_search_service: WebSearchService | None = None


def get_web_search_service() -> WebSearchService:
    global _search_service
    if _search_service is None:
        _search_service = WebSearchService()
    return _search_service
