"""Local environment checker for MyPaperWeb.

Run from the project root:

    python scripts/check_env.py

The script uses only Python standard-library modules so it can run before
project dependencies are installed.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"

REQUIRED_ENV = [
    "DASHSCOPE_API_KEY",
    "MILVUS_HOST",
    "MILVUS_PORT",
    "MILVUS_COLLECTION",
]

RECOMMENDED_ENV = [
    "REDIS_URL",
    "DB_URL",
    "RAG_MODEL",
    "DASHSCOPE_EMBEDDING_MODEL",
    "EMBEDDING_DIM",
]

OPTIONAL_ENV = [
    "WEB_SEARCH_KEY",
    "TAVILY_API_KEY",
    "CORE_API_KEY",
    "RERANK_API_KEY",
]

PLACEHOLDER_MARKERS = (
    "your_",
    "example.com",
    "password",
    "your_dashscope_api_key",
    "your_web_search_key",
    "your_tavily_api_key",
    "your_core_api_key",
    "your_rerank_api_key",
)

PYTHON_IMPORTS = [
    ("fastapi", "FastAPI"),
    ("uvicorn", "Uvicorn"),
    ("pymilvus", "Milvus client"),
    ("langchain", "LangChain"),
    ("langgraph", "LangGraph"),
    ("dotenv", "python-dotenv"),
    ("loguru", "Loguru"),
    ("jieba", "Jieba"),
    ("fitz", "PyMuPDF"),
    ("docx", "python-docx"),
    ("PIL", "Pillow"),
]


@dataclass
class CheckResult:
    level: str
    name: str
    detail: str


class Reporter:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("OK", name, detail))

    def warn(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("WARN", name, detail))

    def fail(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("FAIL", name, detail))

    def print(self) -> None:
        for result in self.results:
            mark = {"OK": "[OK]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[result.level]
            detail = f" - {result.detail}" if result.detail else ""
            print(f"{mark} {result.name}{detail}")

        total_fail = sum(1 for item in self.results if item.level == "FAIL")
        total_warn = sum(1 for item in self.results if item.level == "WARN")
        print()
        print(f"Summary: {total_fail} failed, {total_warn} warning(s), {len(self.results)} check(s)")

    def has_failures(self) -> bool:
        return any(item.level == "FAIL" for item in self.results)

    def has_warnings(self) -> bool:
        return any(item.level == "WARN" for item in self.results)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def merged_env(file_values: dict[str, str]) -> dict[str, str]:
    values = dict(file_values)
    for key, value in os.environ.items():
        values.setdefault(key, value)
    return values


def looks_like_placeholder(value: str) -> bool:
    lowered = (value or "").strip().lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def check_env_files(reporter: Reporter) -> dict[str, str]:
    if ENV_EXAMPLE_PATH.exists():
        reporter.ok(".env.example", ENV_EXAMPLE_PATH.relative_to(PROJECT_ROOT).as_posix())
    else:
        reporter.warn(".env.example", "missing example environment file")

    if not ENV_PATH.exists():
        reporter.fail(".env", "missing .env; copy .env.example to .env and fill real values")
        return {}

    reporter.ok(".env", ENV_PATH.relative_to(PROJECT_ROOT).as_posix())
    return parse_env_file(ENV_PATH)


def check_env_values(reporter: Reporter, env: dict[str, str]) -> None:
    for key in REQUIRED_ENV:
        value = env.get(key, "")
        if looks_like_placeholder(value):
            reporter.fail(key, "missing or still using an example value")
        else:
            reporter.ok(key, "configured")

    for key in RECOMMENDED_ENV:
        value = env.get(key, "")
        if looks_like_placeholder(value):
            reporter.warn(key, "not configured; related feature may not work")
        else:
            reporter.ok(key, "configured")

    for key in OPTIONAL_ENV:
        value = env.get(key, "")
        if looks_like_placeholder(value):
            reporter.warn(key, "optional key not configured")
        else:
            reporter.ok(key, "configured")


def parse_host_port_from_url(raw_url: str) -> tuple[str, int] | None:
    if not raw_url:
        return None

    normalized = raw_url
    if "+aiomysql" in normalized:
        normalized = normalized.replace("+aiomysql", "")
    parsed = urlparse(normalized)
    if not parsed.hostname:
        return None

    default_port = 6379 if parsed.scheme.startswith("redis") else 3306
    return parsed.hostname, parsed.port or default_port


def check_tcp(reporter: Reporter, name: str, host: str, port: int, timeout: float = 1.5) -> None:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            reporter.ok(name, f"{host}:{port} reachable")
    except OSError as exc:
        reporter.warn(name, f"{host}:{port} unreachable ({exc})")


def check_services(reporter: Reporter, env: dict[str, str]) -> None:
    milvus_host = env.get("MILVUS_HOST", "localhost")
    milvus_port = env.get("MILVUS_PORT", "19530")
    if milvus_host and milvus_port.isdigit():
        check_tcp(reporter, "Milvus", milvus_host, int(milvus_port))
    else:
        reporter.fail("Milvus", "MILVUS_HOST or MILVUS_PORT is invalid")

    redis_target = parse_host_port_from_url(env.get("REDIS_URL", ""))
    if redis_target:
        check_tcp(reporter, "Redis", redis_target[0], redis_target[1])
    else:
        reporter.warn("Redis", "REDIS_URL not configured")

    db_target = parse_host_port_from_url(env.get("DB_URL", ""))
    if db_target:
        check_tcp(reporter, "Database", db_target[0], db_target[1])
    else:
        reporter.warn("Database", "DB_URL not configured")


def check_python_imports(reporter: Reporter) -> None:
    for module_name, display_name in PYTHON_IMPORTS:
        if importlib.util.find_spec(module_name) is None:
            reporter.warn(display_name, f"Python module '{module_name}' not importable")
        else:
            reporter.ok(display_name, "importable")


def check_frontend(reporter: Reporter) -> None:
    package_json = PROJECT_ROOT / "frontend" / "package.json"
    node_modules = PROJECT_ROOT / "frontend" / "node_modules"

    if package_json.exists():
        reporter.ok("Frontend package.json", "found")
    else:
        reporter.warn("Frontend package.json", "missing")

    if node_modules.exists():
        reporter.ok("Frontend dependencies", "frontend/node_modules found")
    else:
        reporter.warn("Frontend dependencies", "run 'npm install' in frontend/")


def check_runtime_dirs(reporter: Reporter) -> None:
    for relative in ["uploads", "chat_history", "app/data", "app/data/images", "app/data/notes"]:
        path = PROJECT_ROOT / relative
        if path.exists():
            reporter.ok(relative, "exists")
        else:
            reporter.warn(relative, "will be created at runtime when needed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local MyPaperWeb development environment.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return non-zero for warnings as well as failures",
    )
    args = parser.parse_args()

    reporter = Reporter()
    env_file_values = check_env_files(reporter)
    env = merged_env(env_file_values)

    check_env_values(reporter, env)
    check_python_imports(reporter)
    check_services(reporter, env)
    check_frontend(reporter)
    check_runtime_dirs(reporter)

    reporter.print()

    if reporter.has_failures():
        return 1
    if args.strict and reporter.has_warnings():
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
