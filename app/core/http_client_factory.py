"""HTTP client helpers for model providers.

DashScope requests should bypass system proxy settings by default because
local proxy software may break TLS handshakes for long-running model calls.
"""

from __future__ import annotations

import httpx


DEFAULT_LLM_TIMEOUT = 60.0


def create_llm_http_client(timeout: float = DEFAULT_LLM_TIMEOUT) -> httpx.Client:
    return httpx.Client(trust_env=False, timeout=timeout)


def create_llm_async_http_client(timeout: float = DEFAULT_LLM_TIMEOUT) -> httpx.AsyncClient:
    return httpx.AsyncClient(trust_env=False, timeout=timeout)
