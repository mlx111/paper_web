"""Health report helpers for MyPaperWeb."""

from __future__ import annotations

import socket
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlparse


PLACEHOLDER_MARKERS = (
    "your_",
    "example.com",
    "your_dashscope_api_key",
)


def _looks_configured(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return not any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _service(status: str, message: str, **extra: Any) -> dict[str, Any]:
    data = {"status": status, "message": message}
    data.update(extra)
    return data


def _parse_host_port(raw_url: str, default_port: int) -> tuple[str, int] | None:
    if not raw_url:
        return None

    normalized = raw_url.replace("+aiomysql", "")
    parsed = urlparse(normalized)
    if not parsed.hostname:
        return None
    return parsed.hostname, int(parsed.port or default_port)


def _tcp_reachable(host: str, port: int, timeout: float = 1.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} reachable"
    except OSError as exc:
        return False, f"{host}:{port} unreachable: {exc}"


def _check_optional_url_service(name: str, raw_url: str, default_port: int) -> dict[str, Any]:
    target = _parse_host_port(raw_url, default_port)
    if target is None:
        return _service("warn", f"{name} url is not configured")

    ok, message = _tcp_reachable(target[0], target[1])
    if ok:
        return _service("ok", message)
    return _service("warn", message)


def build_health_report(
    *,
    app_name: str,
    app_version: str,
    debug: bool,
    model_key: str,
    milvus_checker: Callable[[], bool],
    redis_url: str,
    db_url: str,
) -> dict[str, Any]:
    """Build a serializable health report.

    API, model key, and Milvus are treated as required for the RAG app.
    Redis and database are warnings because local demos may run without using
    auth/session features immediately.
    """
    services: dict[str, dict[str, Any]] = {
        "api": _service("ok", "FastAPI application is running"),
        "model_key": (
            _service("ok", "DASHSCOPE_API_KEY is configured")
            if _looks_configured(model_key)
            else _service("error", "DASHSCOPE_API_KEY is missing or still an example value")
        ),
        "redis": _check_optional_url_service("Redis", redis_url, 6379),
        "database": _check_optional_url_service("Database", db_url, 3306),
    }

    try:
        milvus_ok = bool(milvus_checker())
    except Exception as exc:
        milvus_ok = False
        services["milvus"] = _service("error", f"Milvus check raised: {exc}")
    else:
        services["milvus"] = (
            _service("ok", "Milvus is reachable")
            if milvus_ok
            else _service("error", "Milvus is not reachable")
        )

    required_statuses = [
        services["api"]["status"],
        services["model_key"]["status"],
        services["milvus"]["status"],
    ]
    if any(status == "error" for status in required_statuses):
        overall = "error"
    elif any(item["status"] == "warn" for item in services.values()):
        overall = "warn"
    else:
        overall = "ok"

    return {
        "status": overall,
        "app": {
            "name": app_name,
            "version": app_version,
            "debug": bool(debug),
        },
        "checked_at": datetime.now().isoformat(),
        "services": services,
    }
