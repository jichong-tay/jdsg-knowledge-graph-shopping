from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fasthtml.common import to_xml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from shopping.knowledge.models import GraphReadError, GraphViewRequest, SnapshotRef
from shopping.knowledge.projection import canonical_json
from shopping.knowledge.reviews import read_reviews
from shopping.knowledge.snapshot import read_graph_view
from shopping.purchases.families import (
    FamilyError,
    create_family,
    propose_membership,
    review_membership,
)
from shopping.purchases.family_models import EntityType, EvidenceRef, PurchaseScope
from shopping.web.graph_security import PRIVATE_HEADERS, GraphAccessError, GraphSecurity
from shopping.web.graph_views import graph_page
from shopping.web.layout import document, main_view


class _FamilyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=2000)


class _EvidenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entity_type: EntityType
    row_id: int = Field(gt=0, le=2**63 - 1)


class _ProposalBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    product_id: int = Field(gt=0, le=2**63 - 1)
    family_id: int = Field(gt=0, le=2**63 - 1)
    expected_version: int = Field(ge=0, le=2**63 - 1)
    origin: Literal["manual", "inferred"]
    method: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=2000)
    support_refs: tuple[_EvidenceBody, ...] = Field(default=(), max_length=20)


class _ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    proposal_event_id: int = Field(gt=0, le=2**63 - 1)
    expected_version: int = Field(gt=0, le=2**63 - 1)
    decision: Literal["accepted", "rejected", "withdrawn"]
    reason: str = Field(min_length=1, max_length=2000)


class _SnapshotBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_id: str
    source_generation: int = Field(ge=0, le=2**63 - 1)
    projection_schema_version: Literal[1]
    method_version: Literal["delivery-family-v1"]

    @field_validator("projection_schema_version", mode="before")
    @classmethod
    def _strict_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError("invalid snapshot")
        return value


def _valid_query(request: Request, allowed: set[str], cap: int) -> None:
    if len(request.scope.get("query_string", b"")) > cap:
        raise GraphReadError("invalid_input")
    seen: set[str] = set()
    for key, _ in request.query_params.multi_items():
        if key not in allowed or key in seen:
            raise GraphReadError("invalid_input")
        seen.add(key)


def _positive_query(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", value) or len(value) > 20:
        raise GraphReadError("invalid_input")
    result = int(value)
    if result > 2**63 - 1:
        raise GraphReadError("invalid_input")
    return result


def register_graph(app, settings) -> None:
    security = GraphSecurity(settings, app.secret_key)

    async def page(request: Request):
        try:
            security.enforce_read(request)
        except GraphAccessError as exc:
            if exc.code == "missing_configured_origin":
                return HTMLResponse(
                    "Graph needs SHOPPING_APP_ORIGIN configuration.",
                    status_code=503,
                    headers=PRIVATE_HEADERS,
                )
            return _error(exc)
        content = graph_page(
            analysis_date=datetime.now(ZoneInfo("Asia/Singapore")).date().isoformat()
        )
        rendered = (
            main_view("Graph", "Knowledge graph", content, environment=settings.environment)
            if request.headers.get("HX-Request") == "true"
            and request.headers.get("HX-History-Restore-Request") != "true"
            else document(
                "Graph",
                "Knowledge graph",
                content,
                current_path="/graph",
                environment=settings.environment,
            )
        )
        return HTMLResponse(to_xml(rendered), headers=PRIVATE_HEADERS)

    async def token(request: Request):
        try:
            return JSONResponse(security.issue_token(request), headers=PRIVATE_HEADERS)
        except GraphAccessError as exc:
            return _error(exc)

    async def view(request: Request):
        try:
            security.enforce_read(request)
            _valid_query(request, {"request", "snapshot"}, 16384)
            raw = request.query_params.get("request")
            req = (
                GraphViewRequest.model_validate_json(raw)
                if raw is not None
                else GraphViewRequest(
                    purchase_scope=PurchaseScope(datetime.now(ZoneInfo("Asia/Singapore")).date())
                )
            )
            expected = None
            if request.query_params.get("snapshot") is not None:
                snapshot_body = _SnapshotBody.model_validate_json(request.query_params["snapshot"])
                expected = SnapshotRef(
                    snapshot_body.dataset_id,
                    snapshot_body.source_generation,
                    snapshot_body.projection_schema_version,
                    snapshot_body.method_version,
                )
            result = await asyncio.to_thread(
                read_graph_view, settings, req, expected_snapshot=expected
            )
            return JSONResponse(json.loads(canonical_json(result)), headers=PRIVATE_HEADERS)
        except (GraphAccessError, GraphReadError, ValidationError, ValueError) as exc:
            return _error(exc)
        except sqlite3.Error:
            return _error(GraphAccessError("data_unavailable", 503))

    async def reviews(request: Request):
        try:
            security.enforce_read(request)
            _valid_query(request, {"mode", "family_id", "cursor", "limit"}, 4096)
            params = request.query_params
            family_id = _positive_query(params["family_id"]) if "family_id" in params else None
            limit = _positive_query(params.get("limit", "25"))
            if limit > 50:
                raise GraphReadError("invalid_input")
            result = await asyncio.to_thread(
                read_reviews,
                settings,
                mode=params.get("mode", "pending"),
                family_id=family_id,
                cursor=params.get("cursor"),
                limit=limit,
            )
            return JSONResponse(json.loads(canonical_json(result)), headers=PRIVATE_HEADERS)
        except (GraphAccessError, GraphReadError, ValidationError, ValueError) as exc:
            return _error(exc)
        except sqlite3.Error:
            return _error(GraphAccessError("data_unavailable", 503))

    async def family(request: Request):
        return await _write(
            request, security, _FamilyBody, lambda body: create_family(settings, **body), 201
        )

    async def membership(request: Request):
        return await _write(
            request, security, _ProposalBody, lambda body: propose_membership(settings, **body), 200
        )

    async def review(request: Request):
        try:
            security.enforce_write(request)
            raw_id = request.path_params["membership_id"]
            membership_id = int(raw_id)
            if str(membership_id) != raw_id or not 0 < membership_id <= 2**63 - 1:
                raise ValueError
        except GraphAccessError as exc:
            return _error(exc)
        except ValueError:
            return _error(GraphReadError("invalid_input"))
        return await _write(
            request,
            security,
            _ReviewBody,
            lambda body: review_membership(settings, membership_id=membership_id, **body),
            200,
        )

    app.router.routes.extend(
        [
            Route("/graph", page, methods=["GET"]),
            Route("/graph/token", token, methods=["GET"]),
            Route("/graph/view", view, methods=["GET"]),
            Route("/graph/reviews", reviews, methods=["GET"]),
            Route("/graph/families", family, methods=["POST"]),
            Route("/graph/memberships", membership, methods=["POST"]),
            Route("/graph/memberships/{membership_id}/review", review, methods=["POST"]),
        ]
    )


async def _write(request, security, model, operation, status_code):
    try:
        raw = await security.read_json(request)
        body = model.model_validate_json(canonical_json(raw))
        values = body.model_dump()
        if "support_refs" in values:
            values["support_refs"] = tuple(
                EvidenceRef(item["entity_type"], item["row_id"]) for item in values["support_refs"]
            )
        result = await asyncio.to_thread(operation, values)
        return JSONResponse(
            json.loads(canonical_json(result)), status_code=status_code, headers=PRIVATE_HEADERS
        )
    except (GraphAccessError, ValidationError, FamilyError) as exc:
        return _error(exc)
    except sqlite3.Error:
        return _error(GraphAccessError("data_unavailable", 503))


def _error(exc) -> Any:
    code = getattr(exc, "code", "data_unavailable")
    status = getattr(exc, "status", 503)
    if isinstance(exc, ValidationError):
        code, status = "invalid_input", 400
    elif isinstance(exc, GraphReadError):
        status = {
            "invalid_input": 400,
            "not_found": 404,
            "invalid_cursor": 400,
            "stale_snapshot": 409,
            "scope_too_large": 422,
        }.get(exc.code, 503)
    elif isinstance(exc, FamilyError):
        code, status = (
            exc.code,
            {"invalid_input": 400, "not_found": 404, "command_conflict": 409}.get(exc.code, 409),
        )
    elif isinstance(exc, ValueError):
        code, status = "invalid_input", 400
    return JSONResponse({"code": code}, status_code=status, headers=PRIVATE_HEADERS)
