import asyncio
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from shopping.config import Settings
from shopping.web.graph_security import GraphAccessError, GraphSecurity

ORIGIN = "http://127.0.0.1:8000"


def settings(tmp_path: Path, origin: str | None = ORIGIN) -> Settings:
    return Settings(
        environment="development",
        data_dir=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        raw_email_dir=tmp_path / "raw",
        migrations_dir=tmp_path / "migrations",
        app_origin=origin,
    )


def app_for(tmp_path: Path, origin: str | None = ORIGIN) -> Starlette:
    security = GraphSecurity(settings(tmp_path, origin), "test-secret")

    async def token(request: Request):
        try:
            return JSONResponse(security.issue_token(request))
        except GraphAccessError as error:
            return JSONResponse({"code": error.code}, status_code=error.status)

    async def write(request: Request):
        try:
            return JSONResponse(await security.read_json(request))
        except GraphAccessError as error:
            return JSONResponse({"code": error.code}, status_code=error.status)

    app = Starlette(routes=[Route("/token", token), Route("/write", write, methods=["POST"])])
    app.add_middleware(SessionMiddleware, secret_key="session-secret")  # pragma: allowlist secret
    return app


def test_token_and_session_bound_write(tmp_path: Path):
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        response = client.get("/token", headers={"X-Graph-Page": "1"})
        assert response.status_code == 200
        token = response.json()["token"]
        headers = {"Origin": ORIGIN, "X-Graph-Token": token, "Content-Type": "application/json"}
        assert client.post("/write", content=b'{"ok": true}', headers=headers).status_code == 200
        assert (
            client.post(
                "/write", content=b'{"ok": true}', headers={**headers, "X-Graph-Token": "bad"}
            ).status_code
            == 403
        )


def test_origin_and_fetch_site_guards(tmp_path: Path):
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        assert client.get("/token").status_code == 403
        assert (
            client.get(
                "/token", headers={"X-Graph-Page": "1", "Origin": "http://evil.invalid"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/token", headers={"X-Graph-Page": "1", "Sec-Fetch-Site": "same-site"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/token", headers={"X-Graph-Page": "1", "Sec-Fetch-Site": "none"}
            ).status_code
            == 200
        )
    with TestClient(app_for(tmp_path, None), base_url=ORIGIN) as client:
        assert client.get("/token", headers={"X-Graph-Page": "1"}).status_code == 503


@pytest.mark.parametrize("body", [b"[1]", b"{", b'{"x":' + b"[" * 40 + b"]" * 40 + b"}"])
def test_json_is_bounded_and_object_only(tmp_path: Path, body: bytes):
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        token = client.get("/token", headers={"X-Graph-Page": "1"}).json()["token"]
        headers = {"Origin": ORIGIN, "X-Graph-Token": token, "Content-Type": "application/json"}
        assert client.post("/write", content=body, headers=headers).status_code == 400


def test_json_content_type_and_body_cap(tmp_path: Path):
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        token = client.get("/token", headers={"X-Graph-Page": "1"}).json()["token"]
        headers = {"Origin": ORIGIN, "X-Graph-Token": token, "Content-Type": "text/plain"}
        assert client.post("/write", content=b"{}", headers=headers).status_code == 400
        headers["Content-Type"] = "application/json"
        assert (
            client.post("/write", content=b"x" * (16 * 1024 + 1), headers=headers).status_code
            == 400
        )


def test_exact_limit_and_strict_json_numbers(tmp_path: Path):
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        token = client.get("/token", headers={"X-Graph-Page": "1"}).json()["token"]
        headers = {"Origin": ORIGIN, "X-Graph-Token": token, "Content-Type": "application/json"}
        exact = b'{"x":"' + b"a" * (16 * 1024 - 8) + b'"}'
        assert len(exact) == 16 * 1024
        assert client.post("/write", content=exact, headers=headers).status_code == 200
        assert client.post("/write", content=b'{"x":NaN}', headers=headers).status_code == 400
        assert client.post("/write", content=b'{"x":Infinity}', headers=headers).status_code == 400


def test_request_guard_matrix(tmp_path: Path):
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        token_response = client.get("/token", headers={"X-Graph-Page": "1", "Host": "evil.invalid"})
        assert token_response.status_code == 403
        token_response = client.get(
            "/token", headers={"X-Graph-Page": "1", "Sec-Fetch-Site": "cross-site"}
        )
        assert token_response.status_code == 403
        token = client.get("/token", headers={"X-Graph-Page": "1"}).json()["token"]
        base = {"Content-Type": "application/json", "X-Graph-Token": token}
        assert client.post("/write", content=b"{}", headers=base).status_code == 403
        assert (
            client.post(
                "/write", content=b"{}", headers={**base, "Origin": "http://evil.invalid"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/write",
                content=b"{}",
                headers={"Origin": ORIGIN, "Content-Type": "application/json"},
            ).status_code
            == 403
        )


def test_token_expiry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    now = [1000]
    monkeypatch.setattr("itsdangerous.TimestampSigner.get_timestamp", lambda _: now[0])
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        token = client.get("/token", headers={"X-Graph-Page": "1"}).json()["token"]
        headers = {"Origin": ORIGIN, "X-Graph-Token": token, "Content-Type": "application/json"}
        now[0] = 2800
        assert client.post("/write", content=b"{}", headers=headers).status_code == 200
        now[0] = 2801
        assert client.post("/write", content=b"{}", headers=headers).status_code == 403


def test_token_cross_session(tmp_path: Path):
    app = app_for(tmp_path)
    with TestClient(app, base_url=ORIGIN) as first, TestClient(app, base_url=ORIGIN) as second:
        token = first.get("/token", headers={"X-Graph-Page": "1"}).json()["token"]
        headers = {"Origin": ORIGIN, "X-Graph-Token": token, "Content-Type": "application/json"}
        assert second.post("/write", content=b"{}", headers=headers).status_code == 403


def test_bounded_stream_direct_request(tmp_path: Path):
    security = GraphSecurity(settings(tmp_path), "test-secret")
    token = security.signer.sign("session").decode()

    async def run(chunks: list[bytes], content_length: str | None = None):
        calls = iter([*chunks, b""])

        async def receive():
            try:
                body = next(calls)
            except StopIteration:
                body = b""
            return {"type": "http.request", "body": body, "more_body": bool(body)}

        headers = [
            (b"host", b"127.0.0.1:8000"),
            (b"origin", ORIGIN.encode()),
            (b"content-type", b"application/json"),
            (b"x-graph-token", token.encode()),
        ]
        if content_length is not None:
            headers.append((b"content-length", content_length.encode()))
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "headers": headers,
                "session": {"graph_id": "session"},
            },
            receive,
        )
        return await security.read_json(request)

    with pytest.raises(GraphAccessError) as error:
        asyncio.run(run([b'{"x":"' + b"a" * 10000, b"a" * 6380 + b'"}']))
    assert error.value.status == 400
    with pytest.raises(GraphAccessError) as error:
        asyncio.run(run([b"{}"], "1"))
    assert error.value.status == 400


def test_deep_json_500_levels(tmp_path: Path):
    with TestClient(app_for(tmp_path), base_url=ORIGIN) as client:
        token = client.get("/token", headers={"X-Graph-Page": "1"}).json()["token"]
        headers = {"Origin": ORIGIN, "X-Graph-Token": token, "Content-Type": "application/json"}
        body = (b'{"x":' * 500) + b"0" + (b"}" * 500)
        assert client.post("/write", content=body, headers=headers).status_code == 400
