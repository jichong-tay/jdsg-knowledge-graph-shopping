"""Synthetic Chat switching server for browser acceptance checks."""

from __future__ import annotations

import argparse
import importlib.util
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import uvicorn
from starlette.responses import JSONResponse

from shopping.assistant import conversations as saved
from shopping.web import create_app


async def fake_runner(settings, question, *, emit, **kwargs):
    await emit({"type": "text", "text": "Synthetic answer"})
    return {"status": "complete", "code": None, "text": "Synthetic answer", "evidence": []}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8771)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("chat_fixtures", project / "tests/conftest.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load synthetic test fixtures")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix="shopping-chat-browser-") as directory:
        settings = replace(
            module.settings.__wrapped__(Path(directory)), app_origin=f"http://127.0.0.1:{args.port}"
        )
        app = create_app(settings, chat_runner=fake_runner)

        def seed(title):
            cid = saved.new_draft(settings)
            accepted = saved.accept_command(
                settings,
                {"kind": "submit", "id": uuid4().hex, "conversation_id": cid, "text": title},
            )
            attempt = saved.get_attempt(settings, cid, accepted["attempt_id"])
            saved.checkpoint(
                settings,
                cid,
                attempt["id"],
                expected_version=attempt["version"],
                text="Synthetic answer",
                status="complete",
            )
            return cid

        a = seed("Conversation A")
        b = seed("Conversation B")
        app.state.chat_test_ids = {"a": a, "b": b}

        async def remove_b(request):
            outcome = saved.accept_command(
                settings,
                {"kind": "delete", "id": uuid4().hex, "conversation_id": b, "confirmed": True},
            )
            saved.finalize_delete(
                settings, b, expected_version=outcome["version"], cleanup_confirmed=True
            )
            return JSONResponse({"removed": b})

        from starlette.routing import Route

        app.router.routes.append(Route("/test/remove-b", remove_b, methods=["POST"]))
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
