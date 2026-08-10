from __future__ import annotations

import stat
from pathlib import Path

from app.ingestion import import_eml
from app.runtime import get_runtime_info
from app.web import create_app


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
    assert health.json()["database"]["schema_version"] == 1
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
