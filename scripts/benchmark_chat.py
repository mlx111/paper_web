"""Measure chat admission and latency against a running MyPaperWeb backend."""

import argparse
import asyncio
import json
import time
from collections import Counter
from uuid import uuid4

import httpx


def percentile(values: list[float], percentage: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, (percentage * len(ordered) + 99) // 100 - 1)
    return round(ordered[index], 1)


async def run_sample(client: httpx.AsyncClient, path: str, question: str, session_id: str):
    started = time.perf_counter()
    first_content_ms = None
    saw_completion = False
    try:
        async with client.stream(
            "POST", path, json={"Id": session_id, "Question": question}
        ) as response:
            status = response.status_code
            if path.endswith("chat_stream") and status == 200:
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "content" and first_content_ms is None:
                        first_content_ms = (time.perf_counter() - started) * 1000
                    elif event.get("type") in ("done", "complete"):
                        saw_completion = True
                    elif event.get("type") == "error":
                        status = "application_error"
                if status == 200 and not saw_completion:
                    status = "incomplete_stream"
            else:
                await response.aread()
                if status == 200:
                    try:
                        payload = response.json()
                    except ValueError:
                        status = "invalid_response"
                    else:
                        if payload.get("code") != 200 or not payload.get("data", {}).get("success"):
                            status = "application_error"
            return {
                "status": status,
                "total_ms": (time.perf_counter() - started) * 1000,
                "first_content_ms": first_content_ms,
            }
    except httpx.HTTPError as exc:
        return {
            "status": type(exc).__name__,
            "total_ms": (time.perf_counter() - started) * 1000,
            "first_content_ms": None,
        }


async def benchmark(base_url: str, mode: str, count: int, concurrency: int, question: str):
    path = "/agent/chat_stream" if mode == "stream" else "/agent/chat"
    semaphore = asyncio.Semaphore(concurrency)
    prefix = uuid4().hex[:8]
    timeout = httpx.Timeout(120, connect=10)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        async def one(index: int):
            async with semaphore:
                return await run_sample(client, path, question, f"bench-{prefix}-{index}")

        started = time.perf_counter()
        samples = await asyncio.gather(*(one(index) for index in range(count)))
        wall_seconds = time.perf_counter() - started

    statuses = Counter(str(sample["status"]) for sample in samples)
    successful = [sample for sample in samples if sample["status"] == 200]
    latencies = [sample["total_ms"] for sample in successful]
    first_content = [sample["first_content_ms"] for sample in successful if sample["first_content_ms"] is not None]
    return {
        "base_url": base_url,
        "mode": mode,
        "requests": count,
        "client_concurrency": concurrency,
        "wall_seconds": round(wall_seconds, 2),
        "completed_per_second": round(count / wall_seconds, 2),
        "statuses": statuses,
        "successful_latency_ms": {key: percentile(latencies, value) for key, value in (("p50", 50), ("p95", 95), ("p99", 99))},
        "first_content_ms": {key: percentile(first_content, value) for key, value in (("p50", 50), ("p95", 95), ("p99", 99))},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--mode", choices=("chat", "stream"), default="chat")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--question", default="请用一句话解释 RAG。")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")
    result = asyncio.run(benchmark(args.url, args.mode, args.requests, args.concurrency, args.question))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
