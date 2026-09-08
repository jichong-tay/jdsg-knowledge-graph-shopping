import asyncio
import json

import httpx2 as httpx

from app.assistant.ollama import stream_chat


def test_native_stream_assembles_tools_and_sets_required_options(settings):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        chunks = [
            {
                "message": {
                    "content": "Checking ",
                    "tool_calls": [
                        {
                            "function": {
                                "index": 0,
                                "name": "search_products",
                                "arguments": '{"query":',
                            }
                        }
                    ],
                }
            },
            {
                "message": {
                    "content": "history",
                    "tool_calls": [{"function": {"index": 0, "arguments": '"oat"}'}}],
                }
            },
            {"done": True, "done_reason": "stop", "prompt_eval_count": 120, "eval_count": 20},
        ]
        return httpx.Response(200, content="\n".join(json.dumps(c) for c in chunks) + "\n")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return [
                e
                async for e in stream_chat(
                    settings, [{"role": "user", "content": "hello"}], client=client
                )
            ]

    events = asyncio.run(run())
    assert [e["text"] for e in events if e["type"] == "text"] == ["Checking ", "history"]
    assert next(e for e in events if e["type"] == "tools")["calls"] == [
        {"id": "call-0", "name": "search_products", "arguments": {"query": "oat"}}
    ]
    assert events[-1]["type"] == "end"
    request = requests[0]
    assert request["think"] is False
    assert request["truncate"] is False
    assert request["keep_alive"] == "5m"
    assert request["options"] == {"num_ctx": 8192, "num_predict": 768}
    assert len(request["tools"]) == 4


class ChunkStream(httpx.AsyncByteStream):
    """Transport fixture shared by fragmentation, EOF, failure and cancellation checks."""

    def __init__(self, chunks, wait=None):
        self.chunks = chunks
        self.wait = wait
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.wait:
            await self.wait.wait()

    async def aclose(self):
        self.closed = True


def test_byte_fragmentation_and_multiple_complete_proposals(settings):
    raw = (
        json.dumps(
            {
                "message": {
                    "content": "茶",
                    "tool_calls": [
                        {"function": {"name": "search_products", "arguments": {"query": "oat"}}},
                        {"function": {"name": "list_recent_orders", "arguments": {}}},
                    ],
                }
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps({"done": True, "done_reason": "stop"})
        + "\n"
    ).encode()
    transport_stream = ChunkStream([raw[i : i + 1] for i in range(len(raw))])

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=transport_stream)
            )
        ) as client:
            return [event async for event in stream_chat(settings, [], client=client)]

    events = asyncio.run(run())
    assert events[0] == {"type": "text", "text": "茶"}
    assert len(events[1]["calls"]) == 2
    assert events[1]["calls"][1]["id"] == "call-1"
    assert transport_stream.closed


def test_eof_truncation_and_remote_errors_remain_safe(settings):
    cases = [
        (b'{"message":{"content":"Partial"}}\n', "provider_eof"),
        (b'{"done":true,"done_reason":"length"}\n', "output_limit"),
        (b'{"error":"private exception text"}\n', "provider_protocol"),
        (b"not json\n", "provider_protocol"),
        (b'{"message":{"thinking":"unexpected"}}\n', "provider_protocol"),
        (
            b'{"message":{"tool_calls":[{"function":{"name":"x","arguments":"{"}}]}}\n',
            "provider_eof",
        ),
    ]
    for payload, code in cases:
        transport_stream = ChunkStream([payload])

        async def run(transport_stream=transport_stream):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, stream=transport_stream)
                )
            ) as client:
                return [event async for event in stream_chat(settings, [], client=client)]

        events = asyncio.run(run())
        assert events[-1] == {"type": "error", "code": code}
        assert not any(event["type"] == "tools" for event in events)
        assert transport_stream.closed


def test_cancellation_closes_native_http_stream(settings):
    async def run():
        wait = asyncio.Event()
        transport_stream = ChunkStream([b'{"message":{"content":"First"}}\n'], wait)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=transport_stream)
            )
        ) as client:
            entered = asyncio.Event()

            async def consume():
                async for _ in stream_chat(settings, [], client=client):
                    entered.set()

            task = asyncio.create_task(consume())
            await entered.wait()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert transport_stream.closed

    asyncio.run(run())


def test_malformed_nested_tool_objects_return_safe_errors(settings):
    for proposal in [
        None,
        {"function": None},
        {"function": []},
        {"function": {"name": ["bad"], "arguments": {}}},
    ]:

        async def run(proposal=proposal):
            payload = json.dumps({"message": {"tool_calls": [proposal]}}) + "\n"
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload))
            ) as client:
                return [event async for event in stream_chat(settings, [], client=client)]

        assert asyncio.run(run())[-1] == {"type": "error", "code": "provider_protocol"}
