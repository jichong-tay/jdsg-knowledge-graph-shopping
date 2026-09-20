import importlib
import json
import sys
import threading
import time
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.testclient import TestClient

from shopping.assistant import conversations as saved
from shopping.assistant import runtime
from shopping.config import Settings
from shopping.ingestion.pipeline import import_eml
from shopping.storage.schema import migrate
from shopping.web import create_app

sys.path.insert(0, str(Path("tests/web").resolve()))
helpers = importlib.import_module("test_chat_streaming")
connect, initialize, draft, receive = (
    helpers.connect,
    helpers.initialize,
    helpers.draft,
    helpers.receive,
)

release_read = threading.Event()
original_dispatch = runtime.dispatch_tool
original_accept = saved.accept_command


def dispatch(*args):
    assert release_read.wait(2)
    return original_dispatch(*args)


def accept(settings, command):
    if command["kind"] == "stop":
        release_read.set()
        time.sleep(0.15)
    return original_accept(settings, command)


async def count(messages):
    return 100


async def provider(settings, messages):
    yield {
        "type": "tools",
        "calls": [{"id": "call-0", "name": "get_order", "arguments": {"order_id": 1}}],
    }
    yield {"type": "end", "prompt_tokens": 100}


runtime.dispatch_tool = dispatch
saved.accept_command = accept
try:
    with TemporaryDirectory(prefix="shopping-chat-stop-review-") as tmp:
        data = Path(tmp) / "data"
        cfg = Settings(
            environment="development",
            data_dir=data,
            database_path=data / "db",
            raw_email_dir=data / "raw",
            migrations_dir=Path("src/shopping/storage/migrations").resolve(),
            allow_synthetic_fixtures=True,
            app_origin="http://127.0.0.1:8000",
        )
        cfg.prepare_private_directories()
        migrate(cfg.database_path, cfg.migrations_dir)
        import_eml(Path("tests/fixtures/email/fairprice_order_minimal.eml"), cfg)
        app = create_app(
            cfg, chat_runner=partial(runtime.run_attempt, stream=provider, count_input=count)
        )
        with TestClient(app, base_url=cfg.app_origin) as client:
            with connect(client) as socket:
                initialize(client, socket)
                cid = draft(socket)
                socket.send_json(
                    {
                        "v": 1,
                        "type": "submit",
                        "id": "q",
                        "conversation_id": cid,
                        "text": "Read order 1",
                    }
                )
                aid = receive(socket, "ack")["outcome"]["attempt_id"]
                while True:
                    value = receive(socket, "update")
                    if value["attempt"]["tools"]:
                        break
                socket.send_json(
                    {
                        "v": 1,
                        "type": "stop",
                        "id": "stop",
                        "conversation_id": cid,
                        "attempt_id": aid,
                    }
                )
                result = {"stop_ack": receive(socket, "ack")["outcome"]["status"]}
                for _ in range(20):
                    value = socket.receive_json()
                    if value["type"] == "error":
                        result["error"] = value["code"]
                    if value["type"] == "availability":
                        result["availability"] = value["availability"]
                        break
                attempt = saved.get_attempt(cfg, cid, aid)
                result.update(
                    saved_status=attempt["status"],
                    tool_result_saved=attempt["tools"][0]["result"] is not None,
                )
                print(json.dumps(result))
                assert result["availability"] == "available" and attempt["status"] == "stopped", (
                    "Stopping one response faults Chat globally"
                )
finally:
    runtime.dispatch_tool = original_dispatch
    saved.accept_command = original_accept
