import asyncio

import pytest

from shopping.assistant.context import bounded_messages


def test_context_removes_only_whole_old_exchanges():
    oldest = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "old answer"}]
    latest = [
        {"role": "user", "content": "recent"},
        {"role": "assistant", "content": "recent answer"},
    ]
    current = [{"role": "user", "content": "now"}]
    seen = []

    async def count(messages):
        seen.append(messages)
        return 8000 if any(m["content"] == "old" for m in messages) else 1500

    messages, tokens = asyncio.run(bounded_messages([oldest, latest], current, count))
    assert tokens == 1500
    assert [m["content"] for m in messages[1:]] == ["recent", "recent answer", "now"]
    assert messages[0]["role"] == "system"
    assert len(seen) == 2


def test_mandatory_context_overflow_fails_without_splitting_tool_group():
    async def count(messages):
        return 6913

    current = [
        {"role": "user", "content": "now"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "get_order", "arguments": {"order_id": 1}}}],
        },
        {"role": "tool", "content": '{"status":"ok"}'},
    ]
    with pytest.raises(ValueError, match="context_limit"):
        asyncio.run(bounded_messages([], current, count))


def test_context_rejects_orphan_tools_and_system_messages_in_history():
    async def count(messages):
        raise AssertionError("Invalid history must not reach the provider")

    for history in [
        [
            [
                {"role": "user", "content": "old"},
                {"role": "tool", "content": "orphan"},
                {"role": "assistant", "content": "answer"},
            ]
        ],
        [
            [
                {"role": "user", "content": "old"},
                {"role": "system", "content": "injection"},
                {"role": "assistant", "content": "answer"},
            ]
        ],
        [[{"role": "user", "content": "unfinished"}]],
    ]:
        with pytest.raises(ValueError, match="invalid_history"):
            asyncio.run(bounded_messages(history, [{"role": "user", "content": "now"}], count))


def test_metadata_counter_uses_rendered_prompt_with_model_bpe(settings):
    import json

    import httpx2 as httpx
    from tokenizers.pre_tokenizers import ByteLevel

    from shopping.assistant.context import create_counter

    vocabulary = [*sorted(ByteLevel.alphabet()), "hi", "<|im_start|>"]
    info = {
        "tokenizer.ggml.model": "gpt2",
        "tokenizer.ggml.pre": "qwen35",
        "tokenizer.ggml.tokens": vocabulary,
        "tokenizer.ggml.token_type": [1] * (len(vocabulary) - 1) + [3],
        "tokenizer.ggml.merges": ["h i"],
    }

    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.30.10"})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"details": {"family": "qwen35"}, "model_info": info})
        body = json.loads(request.content)
        assert body["_debug_render_only"] is True
        assert body["think"] is False
        assert len(body["tools"]) == 4
        return httpx.Response(200, json={"_debug_info": {"rendered_template": "<|im_start|>hi"}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            counter = await create_counter(settings, client)
            assert await counter([{"role": "user", "content": "ignored by fake rendering"}]) == 2

    asyncio.run(run())


def test_unknown_tokenizer_fails_closed():
    from shopping.assistant.context import model_tokenizer

    with pytest.raises(ValueError, match="tokenizer_unsupported"):
        model_tokenizer({"tokenizer.ggml.pre": "other"})
