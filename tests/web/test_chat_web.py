"""Protected Chat page and initial WebSocket authentication."""

from dataclasses import replace

import pytest
from bs4 import BeautifulSoup
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from shopping.web import create_app

ORIGIN = "http://127.0.0.1:8000"


def token(client):
    response = client.get("/chat/token", headers={"X-Chat-Page": "1"})
    assert response.status_code == 200
    return response.json()["token"]


def test_chat_is_configured_explicitly_and_tokens_are_private(settings):
    with create_app(settings).get_testclient() as client:
        assert client.get("/chat").status_code == 503
    configured = replace(settings, app_origin=ORIGIN)
    with TestClient(create_app(configured), base_url=ORIGIN) as client:
        page = client.get("/chat")
        assert page.status_code == 200
        assert "Ask about your purchases" in page.text
        assert page.headers["cache-control"] == "no-store"
        assert client.get("/chat/token").status_code == 403
        assert token(client)
        cookie = page.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        assert client.get("/chat", headers={"Host": "evil.invalid"}).status_code == 403
        assert (
            client.get(
                "/chat/token", headers={"X-Chat-Page": "1", "Origin": "https://evil.invalid"}
            ).status_code
            == 403
        )
        assert BeautifulSoup(page.text, "html.parser").select_one('textarea[maxlength="4000"]')


@pytest.mark.parametrize("origin", [None, "null", "https://evil.invalid"])
def test_websocket_rejects_unlisted_or_missing_origin(settings, origin):
    with TestClient(create_app(replace(settings, app_origin=ORIGIN)), base_url=ORIGIN) as client:
        token(client)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "ws://127.0.0.1:8000/chat/ws", headers={"Origin": origin} if origin else {}
            ):
                pass


def test_socket_requires_session_bound_first_message_before_any_data(settings):
    with TestClient(create_app(replace(settings, app_origin=ORIGIN)), base_url=ORIGIN) as client:
        page_key = token(client)
        with client.websocket_connect(
            "ws://127.0.0.1:8000/chat/ws", headers={"Origin": ORIGIN}
        ) as socket:
            socket.send_json({"v": 1, "type": "initialize", "id": "init", "token": page_key})
            assert socket.receive_json()["type"] == "ready"
        with client.websocket_connect(
            "ws://127.0.0.1:8000/chat/ws", headers={"Origin": ORIGIN}
        ) as socket:
            socket.send_json({"v": 1, "type": "snapshot", "id": "attack"})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        client.cookies.clear()
        with client.websocket_connect(
            "ws://127.0.0.1:8000/chat/ws", headers={"Origin": ORIGIN}
        ) as socket:
            socket.send_json({"v": 1, "type": "initialize", "id": "init", "token": page_key})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()


@pytest.mark.parametrize("frame", ["{", "[]", '{"v":2}', "x" * 65537])
def test_malformed_and_oversized_frames_close_without_payload_echo(settings, frame):
    with TestClient(create_app(replace(settings, app_origin=ORIGIN)), base_url=ORIGIN) as client:
        page_key = token(client)
        with client.websocket_connect(
            "ws://127.0.0.1:8000/chat/ws", headers={"Origin": ORIGIN}
        ) as socket:
            socket.send_json({"v": 1, "type": "initialize", "id": "init", "token": page_key})
            socket.receive_json()
            socket.send_text(frame)
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 4400


def test_uninitialized_socket_times_out_and_live_token_expires(settings, monkeypatch):
    from shopping.web import chat as web

    monkeypatch.setattr(web, "INITIALIZE_SECONDS", 0.05)
    configured = replace(settings, app_origin=ORIGIN, chat_token_seconds=1)
    with TestClient(create_app(configured), base_url=ORIGIN) as client:
        page_key = token(client)
        with client.websocket_connect(
            "ws://127.0.0.1:8000/chat/ws", headers={"Origin": ORIGIN}
        ) as socket:
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        page_key = token(client)
        with client.websocket_connect(
            "ws://127.0.0.1:8000/chat/ws", headers={"Origin": ORIGIN}
        ) as socket:
            socket.send_json({"v": 1, "type": "initialize", "id": "init", "token": page_key})
            assert socket.receive_json()["type"] == "ready"
            with pytest.raises(WebSocketDisconnect) as expired:
                socket.receive_json()
            assert expired.value.code == 4401


def test_commands_are_rate_limited_per_session_and_heartbeats_are_separate(settings):
    with TestClient(create_app(replace(settings, app_origin=ORIGIN)), base_url=ORIGIN) as client:
        page_key = token(client)
        with client.websocket_connect(
            "ws://127.0.0.1:8000/chat/ws", headers={"Origin": ORIGIN}
        ) as socket:
            socket.send_json({"v": 1, "type": "initialize", "id": "init", "token": page_key})
            socket.receive_json()
            for _ in range(12):
                socket.send_json({"v": 1, "type": "ping"})
                assert socket.receive_json()["type"] == "pong"
            for index in range(9):
                socket.send_json({"v": 1, "type": "status", "id": f"q-{index}", "command_id": None})
                assert socket.receive_json()["type"] == "command_status"
            socket.send_json({"v": 1, "type": "status", "id": "flood", "command_id": None})
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 4429


def test_socket_limit_counts_uninitialized_connections(settings):
    from contextlib import ExitStack

    with TestClient(create_app(replace(settings, app_origin=ORIGIN)), base_url=ORIGIN) as client:
        with ExitStack() as sockets:
            for _ in range(10):
                sockets.enter_context(
                    client.websocket_connect(
                        "ws://127.0.0.1:8000/chat/ws", headers={"Origin": ORIGIN}
                    )
                )
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(
                    "ws://127.0.0.1:8000/chat/ws", headers={"Origin": ORIGIN}
                ):
                    pass


def test_production_cookie_is_secure_and_forwarded_host_cannot_authorize(settings, monkeypatch):
    from shopping.storage.runtime import get_runtime_info

    # Simulate a supported production runtime; all paths remain the synthetic fixture's.
    monkeypatch.setattr(
        "shopping.web.factory.assert_supported_runtime", lambda **_: get_runtime_info()
    )
    configured = replace(
        settings, environment="production", app_origin="https://shopping.example.invalid"
    )
    with TestClient(create_app(configured), base_url="https://shopping.example.invalid") as client:
        page = client.get("/chat")
        assert page.status_code == 200
        assert "secure" in page.headers["set-cookie"].lower()
        assert (
            client.get(
                "/chat",
                headers={"Host": "evil.invalid", "X-Forwarded-Host": "shopping.example.invalid"},
            ).status_code
            == 403
        )
