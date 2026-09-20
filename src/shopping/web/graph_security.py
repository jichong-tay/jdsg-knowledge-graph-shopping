"""Small, independent request guards for the product graph endpoints."""

from __future__ import annotations

import json
import secrets
from urllib.parse import urlsplit

from itsdangerous import BadSignature, TimestampSigner
from starlette.requests import Request

from shopping.config import Settings

GRAPH_TOKEN_MAX_AGE = 30 * 60
GRAPH_BODY_LIMIT = 16 * 1024
PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


class GraphAccessError(Exception):
    """A stable, safe-to-render graph request failure."""

    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status

    def __str__(self) -> str:
        return self.code


def _error(code: str, status: int = 403) -> GraphAccessError:
    return GraphAccessError(code, status)


class GraphSecurity:
    """Enforce graph origin policy and session-bound page tokens."""

    def __init__(self, settings: Settings, secret_key: str) -> None:
        self.settings = settings
        self.signer = TimestampSigner(secret_key, salt="shopping-graph-page-v1")

    def _origin(self, request: Request, *, require_origin: bool) -> None:
        configured = self.settings.app_origin
        if not configured:
            raise _error("missing_configured_origin", 503)
        if request.headers.get("host") != urlsplit(configured).netloc:
            raise _error("forbidden")
        supplied = request.headers.get("origin")
        if require_origin and supplied is None:
            raise _error("forbidden")
        if supplied is not None and supplied != configured:
            raise _error("forbidden")
        if request.headers.get("sec-fetch-site") in {"same-site", "cross-site"}:
            raise _error("forbidden")

    def enforce_read(self, request: Request) -> None:
        self._origin(request, require_origin=False)

    def enforce_write(self, request: Request) -> None:
        self._origin(request, require_origin=True)
        token = request.headers.get("x-graph-token")
        session_id = request.session.get("graph_id")
        if not token or not isinstance(session_id, str):
            raise _error("forbidden")
        try:
            value = self.signer.unsign(token, max_age=GRAPH_TOKEN_MAX_AGE)
        except BadSignature:
            raise _error("forbidden") from None
        if not secrets.compare_digest(value.decode("utf-8"), session_id):
            raise _error("forbidden")

    def issue_token(self, request: Request) -> dict[str, int | str]:
        self.enforce_read(request)
        if request.headers.get("x-graph-page") != "1":
            raise _error("forbidden")
        session_id = request.session.setdefault("graph_id", secrets.token_urlsafe(32))
        return {
            "token": self.signer.sign(session_id).decode("utf-8"),
            "expires_in": GRAPH_TOKEN_MAX_AGE,
        }

    async def read_json(self, request: Request) -> object:
        self.enforce_write(request)
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise _error("invalid_json", 400)
        length = request.headers.get("content-length")
        declared_length: int | None = None
        if length is not None:
            try:
                declared_length = int(length)
                if declared_length > GRAPH_BODY_LIMIT or declared_length < 0:
                    raise ValueError
            except ValueError:
                raise _error("invalid_json", 400) from None
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > GRAPH_BODY_LIMIT:
                raise _error("invalid_json", 400)
            data.extend(chunk)
        if declared_length is not None and len(data) != declared_length:
            raise _error("invalid_json", 400)
        try:
            value = json.loads(bytes(data), parse_constant=_reject_constant)
        except json.JSONDecodeError, RecursionError, UnicodeDecodeError:
            raise _error("invalid_json", 400) from None
        except ValueError:
            raise _error("invalid_json", 400) from None
        if not isinstance(value, dict) or type(value) is not dict:
            raise _error("invalid_json", 400)
        if _json_depth(value) > 32:
            raise _error("invalid_json", 400)
        return value


def _json_depth(value: object, depth: int = 0) -> int:
    if depth > 32:
        return depth
    if type(value) is dict:
        return max([depth, *(_json_depth(item, depth + 1) for item in value.values())])
    if type(value) is list:
        return max([depth, *(_json_depth(item, depth + 1) for item in value)])
    return depth


def _reject_constant(_: str) -> object:
    raise ValueError("non-finite JSON number")
