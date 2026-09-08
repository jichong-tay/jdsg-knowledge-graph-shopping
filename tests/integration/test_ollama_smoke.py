"""Explicit local/homelab acceptance; skipped by default and never uses production data."""

import asyncio
import json
import os
import time

import httpx2 as httpx
import pytest

from app.assistant.ollama import read_metadata
from app.assistant.runtime import run_attempt
from app.ingestion import import_eml

pytestmark = pytest.mark.skipif(
    os.environ.get("SHOPPING_OLLAMA_SMOKE") != "1",
    reason="Set SHOPPING_OLLAMA_SMOKE=1 explicitly for the installed local Qwen model",
)


def test_real_qwen_synthetic_tool_round_trip(settings, fixture_dir):
    # conftest always creates an isolated temporary development DB.
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)

    async def run():
        measurements = []
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            version = await read_metadata(client, settings, "/api/version")
            models = await read_metadata(client, settings, "/api/tags")
            model = next(m for m in models["models"] if m["name"] == settings.ollama_model)
            before = await read_metadata(client, settings, "/api/ps")
            for _ in range(2):
                started = time.monotonic()
                result = await run_attempt(settings, "What is the recorded total for order 1?")
                measurements.append(round(time.monotonic() - started, 2))
                assert result["status"] == "complete", result["code"]
                assert "14.00" in result["text"]
                assert any(e["id"] == "order:1" for e in result["evidence"])
                assert result["tool_calls"] >= 1
            loaded = await read_metadata(client, settings, "/api/ps")
        print(
            json.dumps(
                {
                    "server_version": version["version"],
                    "model": settings.ollama_model,
                    "digest": model["digest"],
                    "think": False,
                    "context": 8192,
                    "initially_loaded": any(
                        m["name"] == settings.ollama_model for m in before["models"]
                    ),
                    "first_seconds": measurements[0],
                    "warm_seconds": measurements[1],
                    "gpu": [
                        {
                            "size": m.get("size"),
                            "size_vram": m.get("size_vram"),
                            "context_length": m.get("context_length"),
                        }
                        for m in loaded["models"]
                        if m["name"] == settings.ollama_model
                    ],
                }
            )
        )

    asyncio.run(run())
