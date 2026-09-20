from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path

from shopping.ingestion.gmail.state import record_gmail_sync_error
from shopping.ingestion.pipeline import import_eml
from shopping.storage.runtime import get_runtime_info
from shopping.web import create_app


def test_dashboard_health_and_order_page(settings, fixture_dir: Path) -> None:
    result = import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    app = create_app(settings)

    session_key = settings.data_dir / ".sesskey"
    assert session_key.exists()
    assert stat.S_IMODE(session_key.stat().st_mode) == 0o600

    with app.get_testclient() as client:
        dashboard = client.get("/")
        health = client.get("/api/health")
        order = client.get(f"/orders/{result.order_id}")
        missing = client.get("/orders/99999")

    assert dashboard.status_code == 200
    assert "EXAMPLE01" in dashboard.text
    assert health.status_code == 200
    assert health.json()["ready"] is get_runtime_info().sqlite_wal_safe
    assert health.json()["database"]["schema_version"] == 3
    assert order.status_code == 200
    assert "Example Oat Drink 1L" in order.text
    assert "SGD 14.00" in order.text
    assert missing.status_code == 404


def test_product_text_is_html_escaped(settings, fixture_dir: Path) -> None:
    raw = (
        (fixture_dir / "fairprice_order_minimal.eml")
        .read_bytes()
        .replace(
            b"Example Oat Drink 1L",
            b"&lt;script&gt;alert(1)&lt;/script&gt; Example Drink 1L",
        )
    )
    malicious = settings.data_dir / "malicious.eml"
    malicious.write_bytes(raw)
    result = import_eml(malicious, settings)
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get(f"/orders/{result.order_id}")

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


def test_empty_dashboard_shows_working_synthetic_import_command(settings) -> None:
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "fairprice_order_minimal.eml --synthetic-fixture" in response.text


def test_application_shell_links_only_to_live_pages(settings) -> None:
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'aria-label="Primary"' in response.text
    assert 'href="/"' in response.text
    assert 'href="/orders"' in response.text
    assert 'href="/system"' in response.text
    assert 'href="/chat"' in response.text
    assert 'href="/graph"' in response.text
    assert "Graph" in response.text


def test_orders_page_exposes_searchable_current_order_history(settings, fixture_dir: Path) -> None:
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get("/orders?q=Oat")

    assert response.status_code == 200
    assert "Orders" in response.text
    assert "Example Oat Drink 1L" in response.text
    assert "EXAMPLE01" in response.text
    assert 'name="q"' in response.text


def test_system_page_exposes_current_operational_state(settings) -> None:
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get("/system")

    assert response.status_code == 200
    assert "System health" in response.text
    assert "SQLite" in response.text
    assert "Ingestion" in response.text


def test_overview_reports_complete_current_facts_and_recorded_value(
    settings, fixture_dir: Path
) -> None:
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Current item lines" in response.text
    assert "Recorded order value" in response.text
    assert "SGD 14.00" in response.text


def test_order_detail_drawer_is_a_dialog_fragment(settings, fixture_dir: Path) -> None:
    result = import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get(
            f"/orders/{result.order_id}?view=drawer",
            headers={"HX-Request": "true", "HX-Target": "drawer-root"},
        )

    assert response.status_code == 200
    assert "<html" not in response.text
    assert 'data-drawer="true"' in response.text
    assert 'role="dialog"' in response.text
    assert 'aria-modal="true"' in response.text
    assert "Example Oat Drink 1L" in response.text


def test_order_detail_shows_source_ordered_revision_history(settings, fixture_dir: Path) -> None:
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    result = import_eml(fixture_dir / "fairprice_order_adjusted.eml", settings)
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get(f"/orders/{result.order_id}")

    assert response.status_code == 200
    assert "Revision history" in response.text
    assert 'data-revision-count="2"' in response.text
    assert "Current factual revision" in response.text
    assert "Historical revision" in response.text


def test_system_page_reports_current_gmail_error_without_raw_account_data(settings) -> None:
    record_gmail_sync_error(
        settings.database_path,
        account_key="private.person@example.invalid",
        scan_watermark_at=datetime(2026, 8, 25, tzinfo=UTC),
        error_code="gmail_oauth_expired",
    )
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get("/system")

    assert response.status_code == 200
    assert "Gmail sync" in response.text
    assert "gmail_oauth_expired" in response.text
    assert "private.person@example.invalid" not in response.text


def test_system_page_does_not_hide_an_error_behind_a_newer_success(settings, monkeypatch) -> None:
    def snapshot(_database_path):
        return {
            "ingestion": {},
            "gmail_sync": [
                {
                    "last_success_at": "2026-08-25T12:00:00+00:00",
                    "last_error_at": None,
                    "last_error": "source_error",
                    "updated_at": "2026-08-25T12:00:00+00:00",
                },
                {
                    "last_success_at": None,
                    "last_error_at": "2026-08-25T11:00:00+00:00",
                    "last_error": "gmail_oauth_expired",
                    "updated_at": "2026-08-25T11:00:00+00:00",
                },
            ],
            "normalization": {
                "provisional": 0,
                "rejected": 0,
                "unreviewed_aliases": 0,
            },
        }

    monkeypatch.setattr("shopping.web.system.system_snapshot", snapshot)
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get("/system")

    assert response.status_code == 200
    assert "gmail_oauth_expired" in response.text


def test_overview_includes_delivery_and_recent_ingestion_regions(
    settings, fixture_dir: Path
) -> None:
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Scheduled deliveries" in response.text
    assert "Recent ingestion" in response.text
    assert "Manual source" in response.text


def test_order_history_exposes_safe_source_evidence(settings, fixture_dir: Path) -> None:
    result = import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    raw_hash_prefix = Path(result.archived_path).stem[:8]
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get(f"/orders/{result.order_id}")

    assert response.status_code == 200
    assert "Source evidence" in response.text
    assert "Manual source" in response.text
    assert raw_hash_prefix in response.text
    assert str(settings.raw_email_dir) not in response.text


def test_volatile_htmx_regions_have_standalone_refresh_routes(settings) -> None:
    app = create_app(settings)

    with app.get_testclient() as client:
        overview = client.get("/")
        attention = client.get("/fragments/attention", headers={"HX-Request": "true"})
        system = client.get("/fragments/system-health", headers={"HX-Request": "true"})

    assert 'hx-get="/fragments/attention"' in overview.text
    assert attention.status_code == 200
    assert 'id="attention-region"' in attention.text
    assert system.status_code == 200
    assert 'id="system-health-region"' in system.text


def test_order_page_uses_current_revision_listing_name(
    settings, fixture_dir: Path, tmp_path: Path
) -> None:
    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    later_raw = (
        (fixture_dir / "fairprice_order_adjusted.eml")
        .read_bytes()
        .replace(
            b"Example Sparkling Drink &amp; Mixer 4 Pack",
            b"Example Updated Listing 4 Pack",
            1,
        )
    )
    later_path = tmp_path / "renamed-listing.eml"
    later_path.write_bytes(later_raw)
    result = import_eml(later_path, settings)
    app = create_app(settings)

    with app.get_testclient() as client:
        response = client.get(f"/orders/{result.order_id}")

    assert response.status_code == 200
    assert "Example Updated Listing 4 Pack" in response.text
    assert "Example Oat Drink 1L" not in response.text
    assert "Other fees: SGD 0.40" in response.text
    assert "Included tax: SGD 1.24" in response.text


def test_product_evidence_page_is_paginated_and_links_to_orders(purchase_facts):
    from urllib.parse import parse_qs, urlparse

    from bs4 import BeautifulSoup

    app = create_app(purchase_facts)
    with app.get_testclient() as client:
        response = client.get("/products/1")
        assert response.status_code == 200
        assert "Purchase date" in response.text
        assert "12 Jan 2026" in response.text
        soup = BeautifulSoup(response.text, "html.parser")
        next_link = soup.find("a", string="Next →")
        assert next_link is not None
        url = str(next_link.get("href"))
        assert parse_qs(urlparse(url).query)["cursor"]
        assert client.get(url).status_code == 200
        for link in soup.select('a[href^="/orders/"]'):
            assert client.get(str(link.get("href"))).status_code == 200
        assert client.get("/products/999").status_code == 404
        assert client.get("/products/1?cursor=bad").status_code == 400
        assert client.get("/products/0").status_code == 400


def test_product_evidence_escapes_names_and_displays_singapore_date(purchase_facts):
    from shopping.storage.connection import connect_database

    connection = connect_database(purchase_facts.database_path)
    try:
        connection.execute(
            "UPDATE products SET canonical_name = ? WHERE id = 1",
            ('<img src="https://evil.invalid/x" onerror="alert(1)">',),
        )
    finally:
        connection.close()
    app = create_app(purchase_facts)
    with app.get_testclient() as client:
        url = "/products/1"
        texts = []
        from bs4 import BeautifulSoup

        while url:
            response = client.get(url)
            assert response.status_code == 200
            assert "&lt;img" in response.text
            assert '<img src="https://evil.invalid' not in response.text
            texts.append(response.text)
            link = BeautifulSoup(response.text, "html.parser").find("a", string="Next →")
            url = str(link.get("href")) if link else ""
        assert "11 Jan 2026" in "".join(texts)  # 10 Jan 18:00 UTC is 11 Jan in Singapore.
        assert "Unavailable" in "".join(texts)
