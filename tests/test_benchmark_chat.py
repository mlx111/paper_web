import asyncio
import importlib.util
from pathlib import Path

import httpx


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_chat.py"
spec = importlib.util.spec_from_file_location("benchmark_chat", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_nearest_rank_percentile():
    assert module.percentile([1, 2, 3, 4], 50) == 2
    assert module.percentile([1, 2, 3, 4], 95) == 4
    assert module.percentile([], 95) is None


def test_stream_sample_records_first_content():
    def handler(request):
        assert request.url.path == "/agent/chat_stream"
        return httpx.Response(
            200,
            text='data: {"type":"context","data":{}}\n\ndata: {"type":"content","data":"hi"}\n\ndata: {"type":"done","data":{}}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test") as client:
            return await module.run_sample(client, "/agent/chat_stream", "question", "session")

    result = asyncio.run(run())
    assert result["status"] == 200
    assert result["first_content_ms"] is not None
    assert result["total_ms"] >= result["first_content_ms"]


def test_chat_business_error_is_not_counted_as_success():
    def handler(request):
        return httpx.Response(200, json={"code": 500, "data": {"success": False}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test") as client:
            return await module.run_sample(client, "/agent/chat", "question", "session")

    assert asyncio.run(run())["status"] == "application_error"


def test_stream_without_completion_is_not_counted_as_success():
    def handler(request):
        return httpx.Response(200, text='data: {"type":"content","data":"partial"}\n\n')

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test") as client:
            return await module.run_sample(client, "/agent/chat_stream", "question", "session")

    assert asyncio.run(run())["status"] == "incomplete_stream"
