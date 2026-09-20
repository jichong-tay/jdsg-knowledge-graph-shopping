import json
from dataclasses import replace
from uuid import uuid4

import pytest

from shopping.web import create_app

ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def graph_client(settings, fixture_dir):
    from shopping.ingestion.pipeline import import_eml

    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    app = create_app(replace(settings, app_origin=ORIGIN))
    with app.get_testclient(base_url=ORIGIN) as client:
        yield client


def test_graph_shell_and_token_guard(settings):
    app = create_app(replace(settings, app_origin=ORIGIN))
    with app.get_testclient() as client:
        shell = client.get("/graph", headers={"host": "127.0.0.1:8000"})
        denied = client.get("/graph/token", headers={"host": "127.0.0.1:8000", "Origin": ORIGIN})
        token = client.get(
            "/graph/token",
            headers={"host": "127.0.0.1:8000", "Origin": ORIGIN, "X-Graph-Page": "1"},
        )
    assert shell.status_code == 200
    assert 'id="shopping-graph"' in shell.text
    assert 'id="graph-canvas"' in shell.text
    assert 'id="graph-coverage-note"' in shell.text
    assert 'data-graph-action="focus"' in shell.text
    assert 'name="query"' in shell.text and "Filters" in shell.text
    assert 'hx-history="false"' in shell.text
    for action in (
        "zoom-in",
        "zoom-out",
        "fit",
        "reset",
        "refresh",
        "overview-next",
        "reviews",
        "reviews-next",
    ):
        assert f'data-graph-action="{action}"' in shell.text
    for node_type in (
        "order",
        "revision",
        "item",
        "listing",
        "product",
        "family",
        "retailer",
        "source",
    ):
        assert f'value="{node_type}"' in shell.text
    assert shell.text.index('id="graph-status"') < shell.text.index('id="graph-error"')
    assert denied.status_code == 403
    assert token.status_code == 200
    assert token.json()["expires_in"] == 1800


def test_graph_missing_origin_configuration(settings):
    app = create_app(settings)
    with app.get_testclient() as client:
        response = client.get("/graph")
    assert response.status_code == 503
    assert "Graph needs SHOPPING_APP_ORIGIN configuration." in response.text


def test_graph_view_empty_database_returns_json(settings):
    app = create_app(replace(settings, app_origin=ORIGIN))
    with app.get_testclient(base_url=ORIGIN) as client:
        response = client.get(
            "/graph/view",
            params={"request": json.dumps({"purchase_scope": {"analysis_date": "2026-09-20"}})},
            headers={"Origin": ORIGIN, "Host": "127.0.0.1:8000"},
        )
    assert response.status_code == 200
    assert response.json()["nodes"] == []
    assert response.json()["edges"] == []
    assert response.json()["scope"]["analysis_date"] == "2026-09-20"


def test_graph_view_rejects_stale_snapshot(graph_client):
    headers = {"Origin": ORIGIN, "Host": "127.0.0.1:8000"}
    first = graph_client.get("/graph/view", headers=headers)
    assert first.status_code == 200
    snapshot = first.json()["snapshot"]
    token = graph_client.get("/graph/token", headers={**headers, "X-Graph-Page": "1"}).json()[
        "token"
    ]
    created = graph_client.post(
        "/graph/families",
        json={"command_id": uuid4().hex, "name": "Changes", "definition": "Products"},
        headers={**headers, "X-Graph-Token": token},
    )
    assert created.status_code == 201
    response = graph_client.get(
        "/graph/view",
        params={"snapshot": json.dumps(snapshot)},
        headers=headers,
    )
    assert response.status_code == 409, response.text
    assert response.json() == {"code": "stale_snapshot"}


@pytest.mark.parametrize(
    "path", ["/graph/families", "/graph/memberships", "/graph/memberships/1/review"]
)
@pytest.mark.parametrize("headers", [{}, {"Origin": ORIGIN}, {"Origin": "http://evil.invalid"}])
def test_graph_write_routes_require_origin_and_token(graph_client, path, headers):
    response = graph_client.post(path, json={}, headers={"Host": "127.0.0.1:8000", **headers})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_graph_view_rejects_malformed_snapshot(graph_client):
    headers = {"Origin": ORIGIN, "Host": "127.0.0.1:8000"}
    for snapshot in (
        {
            "dataset_id": "bad",
            "source_generation": 0,
            "projection_schema_version": 1,
            "method_version": "delivery-family-v1",
        },
        {
            "dataset_id": "a" * 32,
            "source_generation": 0,
            "projection_schema_version": True,
            "method_version": "delivery-family-v1",
        },
    ):
        response = graph_client.get(
            "/graph/view", params={"snapshot": json.dumps(snapshot)}, headers=headers
        )
        assert response.status_code == 400
        assert response.json() == {"code": "invalid_input"}


def test_graph_command_replay_and_withdrawal(graph_client):
    headers = {"Origin": ORIGIN, "Host": "127.0.0.1:8000"}
    token = graph_client.get("/graph/token", headers={**headers, "X-Graph-Page": "1"}).json()[
        "token"
    ]
    write_headers = {**headers, "X-Graph-Token": token}
    payload = {"command_id": uuid4().hex, "name": "Replay family", "definition": "Products"}
    created = graph_client.post("/graph/families", json=payload, headers=write_headers)
    replay = graph_client.post("/graph/families", json=payload, headers=write_headers)
    assert created.status_code == replay.status_code == 201 and created.json() == replay.json()
    assert (
        graph_client.post(
            "/graph/families", json={**payload, "name": "Changed"}, headers=write_headers
        ).status_code
        == 409
    )
    proposal = graph_client.post(
        "/graph/memberships",
        json={
            "command_id": uuid4().hex,
            "product_id": 1,
            "family_id": created.json()["id"],
            "expected_version": 0,
            "origin": "manual",
            "method": "test",
            "rationale": "support",
            "support_refs": [{"entity_type": "product", "row_id": 1}],
        },
        headers=write_headers,
    )
    assert proposal.status_code == 200 and proposal.json()["support_refs"][0]["row_id"] == 1
    accept = {
        "command_id": uuid4().hex,
        "proposal_event_id": proposal.json()["event_id"],
        "expected_version": 1,
        "decision": "accepted",
        "reason": "yes",
    }
    accepted = graph_client.post(
        f"/graph/memberships/{proposal.json()['id']}/review", json=accept, headers=write_headers
    )
    withdrawn = graph_client.post(
        f"/graph/memberships/{proposal.json()['id']}/review",
        json={
            **accept,
            "command_id": uuid4().hex,
            "expected_version": 2,
            "decision": "withdrawn",
            "reason": "change",
        },
        headers=write_headers,
    )
    assert accepted.status_code == withdrawn.status_code == 200
    retry = graph_client.post(
        f"/graph/memberships/{proposal.json()['id']}/review", json=accept, headers=write_headers
    )
    assert retry.status_code == 200 and retry.json() == accepted.json()
    assert (
        graph_client.post(
            f"/graph/memberships/{proposal.json()['id']}/review",
            json={**accept, "command_id": uuid4().hex},
            headers=write_headers,
        ).status_code
        == 409
    )
    history = graph_client.get(
        f"/graph/reviews?mode=history&family_id={created.json()['id']}", headers=headers
    ).json()
    assert [entry["state"] for entry in history["entries"]] == ["pending", "accepted", "withdrawn"]


def test_graph_membership_workflow(graph_client):
    headers = {"Origin": ORIGIN, "Host": "127.0.0.1:8000"}
    token = graph_client.get("/graph/token", headers={**headers, "X-Graph-Page": "1"}).json()[
        "token"
    ]
    write_headers = {**headers, "X-Graph-Token": token}
    family_payload = {"command_id": "a" * 32, "name": "Graph family", "definition": "Products"}
    created = graph_client.post("/graph/families", json=family_payload, headers=write_headers)
    assert created.status_code == 201
    family_id = created.json()["id"]
    proposal = graph_client.post(
        "/graph/memberships",
        json={
            "command_id": "b" * 32,
            "product_id": 1,
            "family_id": family_id,
            "expected_version": 0,
            "origin": "manual",
            "method": "test",
            "rationale": "review",
        },
        headers=write_headers,
    )
    assert proposal.status_code == 200
    proposal_body = proposal.json()
    assert graph_client.get("/graph/reviews?mode=pending", headers=headers).json()["entries"]
    review = graph_client.post(
        f"/graph/memberships/{proposal_body['id']}/review",
        json={
            "command_id": "c" * 32,
            "proposal_event_id": proposal_body["event_id"],
            "expected_version": 1,
            "decision": "accepted",
            "reason": "yes",
        },
        headers=write_headers,
    )
    assert review.status_code == 200
    assert (
        graph_client.get("/graph/reviews?mode=current", headers=headers).json()["entries"][0][
            "state"
        ]
        == "accepted"
    )


@pytest.mark.parametrize(
    "path",
    [
        "/graph/view?unknown=1",
        "/graph/view?request=a&request=b",
        "/graph/view?request=",
        "/graph/view?request={",
        "/graph/reviews?mode=pending&mode=current",
        "/graph/reviews?limit=0",
        "/graph/reviews?limit=51",
        "/graph/reviews?limit=true",
        "/graph/reviews?limit=%2B1",
        "/graph/reviews?limit=01",
        "/graph/reviews?family_id=0",
        "/graph/reviews?family_id=9223372036854775808",
        "/graph/reviews?cursor=!",
    ],
)
def test_graph_get_query_guard_matrix(graph_client, path):
    response = graph_client.get(path, headers={"Origin": ORIGIN, "Host": "127.0.0.1:8000"})
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"


def test_graph_oversized_query_is_rejected(graph_client):
    response = graph_client.get(
        "/graph/view?request=" + "a" * 16385,
        headers={"Origin": ORIGIN, "Host": "127.0.0.1:8000"},
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": ORIGIN, "Host": "evil.invalid"},
        {"Origin": "http://evil.invalid", "Host": "127.0.0.1:8000"},
        {"Origin": ORIGIN, "Host": "127.0.0.1:8000", "Sec-Fetch-Site": "same-site"},
    ],
)
def test_graph_read_endpoints_reject_origin_guards(graph_client, headers):
    for path in ("/graph/token", "/graph/view", "/graph/reviews"):
        response = graph_client.get(path, headers=headers)
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"


def test_graph_write_body_guard_matrix(graph_client):
    headers = {"Origin": ORIGIN, "Host": "127.0.0.1:8000"}
    token = graph_client.get("/graph/token", headers={**headers, "X-Graph-Page": "1"}).json()[
        "token"
    ]
    write = {**headers, "X-Graph-Token": token}
    cases = [
        ("application/json", b"{"),
        ("text/plain", b"{}"),
        (
            "application/json",
            b'{"command_id":"' + b"a" * 32 + b'","name":"x","definition":"y","extra":1}',
        ),
        ("application/json", b'{"command_id":true,"name":"x","definition":"y"}'),
        ("application/json", b'{"command_id":"bad","name":"x","definition":"y"}'),
    ]
    for content_type, body in cases:
        response = graph_client.post(
            "/graph/families", content=body, headers={**write, "content-type": content_type}
        )
        assert response.status_code == 400
    response = graph_client.post(
        "/graph/families",
        content=b"{" + b"a" * 17000,
        headers={**write, "content-type": "application/json"},
    )
    assert response.status_code == 400


def test_graph_cross_session_token_rejected(graph_client):
    headers = {"Origin": ORIGIN, "Host": "127.0.0.1:8000"}
    token = graph_client.get("/graph/token", headers={**headers, "X-Graph-Page": "1"}).json()[
        "token"
    ]
    with graph_client.app.get_testclient(base_url=ORIGIN) as second:
        response = second.post(
            "/graph/families",
            json={"command_id": uuid4().hex, "name": "x", "definition": "y"},
            headers={**headers, "X-Graph-Token": token},
        )
    assert response.status_code == 403


def test_graph_shell_scripts_and_htmx_fragment(graph_client):
    headers = {"Origin": ORIGIN, "Host": "127.0.0.1:8000"}
    full = graph_client.get("/graph", headers=headers)
    fragment = graph_client.get("/graph", headers={**headers, "HX-Request": "true"})
    assert full.text.count("/static/graph.js") == 1
    assert fragment.text.count("/static/graph.js") == 0
    assert 'id="main-view"' in fragment.text
    restored = graph_client.get(
        "/graph",
        headers={**headers, "HX-Request": "true", "HX-History-Restore-Request": "true"},
    )
    assert 'class="app-shell"' in restored.text
    assert 'id="app-sidebar"' in restored.text
    assert restored.text.count("/static/graph.js") == 1
