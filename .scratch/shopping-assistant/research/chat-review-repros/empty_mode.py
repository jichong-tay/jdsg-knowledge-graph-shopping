import asyncio
import json
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.testclient import TestClient

import shopping.config as config
from shopping.assistant import conversations as saved
from shopping.assistant.runtime import run_attempt
from shopping.config import Settings
from shopping.storage.schema import migrate
from shopping.web import create_app

ORIGIN = "http://127.0.0.1:8000"


async def count(messages):
    return 100


async def provider(settings, messages):
    yield {"type": "text", "text": "[[unsupported]]"}
    yield {"type": "end", "prompt_tokens": 100}


with TemporaryDirectory(prefix="shopping-chat-review-") as temporary:
    root = Path(temporary)
    settings = Settings(
        environment="development",
        data_dir=root / "data",
        database_path=root / "data" / "shopping.sqlite3",
        raw_email_dir=root / "data" / "raw-email",
        migrations_dir=Path(config.__file__).parent / "storage" / "migrations",
        app_origin=ORIGIN,
    )
    settings.prepare_private_directories()
    migrate(settings.database_path, settings.migrations_dir)
    direct = asyncio.run(
        run_attempt(
            settings, "Can you predict a future purchase?", stream=provider, count_input=count
        )
    )
    print(
        json.dumps({"runtime_status": direct["status"], "runtime_text_length": len(direct["text"])})
    )
    runner = partial(run_attempt, stream=provider, count_input=count)
    with TestClient(create_app(settings, chat_runner=runner), base_url=ORIGIN) as client:
        token = client.get("/chat/token", headers={"X-Chat-Page": "1"}).json()["token"]
        with client.websocket_connect(
            ORIGIN.replace("http:", "ws:") + "/chat/ws", headers={"Origin": ORIGIN}
        ) as socket:
            socket.send_json({"v": 1, "type": "initialize", "id": "init", "token": token})
            assert socket.receive_json()["type"] == "ready"
            socket.send_json({"v": 1, "type": "subscribe", "id": "new", "conversation_id": None})
            while True:
                value = socket.receive_json()
                if value["type"] == "draft":
                    cid = value["conversation_id"]
                    break
            socket.send_json(
                {
                    "v": 1,
                    "type": "submit",
                    "id": "send",
                    "conversation_id": cid,
                    "text": "Can you predict a future purchase?",
                }
            )
            observed = {}
            for _ in range(30):
                value = socket.receive_json()
                if value["type"] == "ack":
                    aid = value["outcome"]["attempt_id"]
                elif value["type"] == "error":
                    observed["error"] = value["code"]
                elif value["type"] == "availability":
                    observed["availability"] = value["availability"]
                    break
            observed["saved_attempt_status"] = saved.get_attempt(settings, cid, aid)["status"]
            socket.send_json(
                {
                    "v": 1,
                    "type": "submit",
                    "id": "second",
                    "conversation_id": cid,
                    "text": "What can you do?",
                }
            )
            for _ in range(30):
                value = socket.receive_json()
                if value["type"] == "error":
                    observed["next_send_error"] = value["code"]
                    break
            print(json.dumps(observed))
            assert observed["availability"] == "available", (
                "One malformed answer disables all subsequent Chat generation"
            )
