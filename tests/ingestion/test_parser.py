from __future__ import annotations

import socket
import urllib.request
from pathlib import Path

import pytest

from shopping.ingestion.parsers import (
    UnsupportedEmailError,
    parse_fairprice_email,
    parse_order_email,
)
from shopping.ingestion.parsers.fairprice import parse_sgd_cents

_TEST_DOMAINS = frozenset({"fairprice.example.invalid"})


def _fixture(fixture_dir: Path, name: str) -> bytes:
    return (fixture_dir / name).read_bytes()


def _parse(raw: bytes, *, source_message_key: str | None = None):
    return parse_fairprice_email(
        raw,
        source_message_key=source_message_key,
        allowed_sender_domains=_TEST_DOMAINS,
    )


def test_parses_direct_html_order(fixture_dir: Path) -> None:
    parsed = _parse(_fixture(fixture_dir, "fairprice_order_minimal.eml"))

    assert parsed.order.retailer_slug == "fairprice"
    assert parsed.order.retailer_country == "SG"
    assert parsed.order.external_order_id == "EXAMPLE01"
    assert parsed.order.revision_kind == "confirmation"
    assert parsed.order.status == "placed"
    assert parsed.order.ordered_at is None
    assert parsed.metadata.source_sent_at is not None
    assert parsed.metadata.source_sent_at.isoformat() == "2026-01-11T10:00:00+08:00"
    assert parsed.order.delivery_at is not None
    assert parsed.order.delivery_at.isoformat() == "2026-01-12T18:00:00+08:00"
    assert len(parsed.order.items) == 2
    assert parsed.order.items[0].name == "Example Oat Drink 1L"
    assert parsed.order.items[0].quantity == 2
    assert parsed.order.items[0].unit_price_cents == 400
    assert parsed.order.items[0].gross_cents == 800
    assert parsed.order.items[0].discount_cents == 0
    assert parsed.order.subtotal_cents == 1_150
    assert parsed.order.discount_cents == 100
    assert parsed.order.delivery_fee_cents == 300
    assert parsed.order.service_fee_cents == 50
    assert parsed.order.other_fee_cents == 0
    assert parsed.order.tax_cents == 0
    assert parsed.order.included_tax_cents == 0
    assert parsed.order.total_cents == 1_400
    assert parsed.metadata.original_message_id == ("<fairprice-order-example01-v1@example.invalid>")


def test_parses_later_adjusted_business_facts(fixture_dir: Path) -> None:
    parsed = _parse(_fixture(fixture_dir, "fairprice_order_adjusted.eml"))

    assert parsed.order.external_order_id == "EXAMPLE01"
    assert parsed.order.revision_kind == "confirmation"
    assert parsed.order.ordered_at is None
    assert parsed.metadata.source_sent_at is not None
    assert parsed.metadata.source_sent_at.isoformat() == "2026-01-11T11:30:00+08:00"
    assert len(parsed.order.items) == 2
    assert parsed.order.items[0].name == "Example Sparkling Drink & Mixer 4 Pack"
    assert parsed.order.items[0].gross_cents == 1_000
    assert parsed.order.items[0].discount_cents == 100
    assert parsed.order.items[0].net_cents == 900
    assert parsed.order.subtotal_cents == 1_700
    assert parsed.order.discount_cents == 150
    assert parsed.order.delivery_fee_cents == 200
    assert parsed.order.service_fee_cents == 100
    assert parsed.order.other_fee_cents == 40
    assert parsed.order.tax_cents == 0
    assert parsed.order.included_tax_cents == 124
    assert parsed.order.total_cents == 1_890


def test_forwarded_wrapper_preserves_original_business_fingerprint(fixture_dir: Path) -> None:
    direct = _parse(_fixture(fixture_dir, "fairprice_order_minimal.eml"))
    forwarded = _parse(_fixture(fixture_dir, "fairprice_order_forwarded_again.eml"))

    assert forwarded.order == direct.order
    assert forwarded.metadata.source_fingerprint == direct.metadata.source_fingerprint
    assert forwarded.metadata.original_message_id == direct.metadata.original_message_id
    assert forwarded.metadata.rfc822_message_id != direct.metadata.rfc822_message_id
    assert forwarded.metadata.received_at.isoformat() == "2026-01-12T08:00:00+08:00"
    assert forwarded.metadata.source_sent_at == direct.metadata.source_sent_at


def test_delivery_weekday_must_match_the_numeric_date(fixture_dir: Path) -> None:
    # 12 Jan 2026 is a Monday; claiming Sunday is an internal contradiction.
    raw = _fixture(fixture_dir, "fairprice_order_minimal.eml").replace(
        b"Mon, 12 Jan", b"Sun, 12 Jan"
    )

    with pytest.raises(UnsupportedEmailError, match="E_DELIVERY_TIME"):
        _parse(raw)


def test_truncated_multipart_boundary_is_rejected(fixture_dir: Path) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_forwarded_again.eml")
    assert raw.rstrip(b"\n").endswith(b"--example-forward-boundary--")
    truncated = raw.rsplit(b"\n--example-forward-boundary--", 1)[0] + b"\n"

    with pytest.raises(UnsupportedEmailError, match="E_MIME"):
        _parse(truncated)


def test_neutral_dispatcher_keeps_synthetic_domain_opt_in(fixture_dir: Path) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_minimal.eml")

    with pytest.raises(UnsupportedEmailError, match="E_VENDOR_LAYOUT"):
        parse_order_email(raw)
    parsed = parse_order_email(raw, allow_synthetic_fixtures=True)

    assert parsed.order.external_order_id == "EXAMPLE01"


def test_source_message_key_override_is_preserved(fixture_dir: Path) -> None:
    parsed = _parse(
        _fixture(fixture_dir, "fairprice_order_minimal.eml"),
        source_message_key="manual:example-source",
    )

    assert parsed.metadata.source_message_key == "manual:example-source"


def test_default_adapter_domains_reject_reserved_fixture_sender(fixture_dir: Path) -> None:
    with pytest.raises(UnsupportedEmailError, match="E_VENDOR_LAYOUT"):
        parse_fairprice_email(_fixture(fixture_dir, "fairprice_order_minimal.eml"))


def test_rejects_unsupported_message(fixture_dir: Path) -> None:
    with pytest.raises(UnsupportedEmailError, match="E_VENDOR_LAYOUT"):
        _parse(_fixture(fixture_dir, "unsupported.eml"))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"orders@fairprice.example.invalid", b"attacker@example.invalid"),
        (b"<tr><td>EXAMPLE01</td></tr>", b"<tr><td>DIFFERENT1</td></tr>"),
        (b"<tr><td>2</td></tr>", b"<tr><td>1e2</td></tr>"),
        (b"S$4.00 / item", b"S$1e3 / item"),
        (b"<tr><td>2 item(s)</td></tr>", b"<tr><td>3 item(s)</td></tr>"),
        (b"<tr><td>-S$1.00</td></tr>", b"<tr><td>S$1.00</td></tr>"),
        (b"<tr><td>6pm - 8pm</td></tr>", b"<tr><td>sometime later</td></tr>"),
    ],
)
def test_rejects_untrusted_or_ambiguous_values(fixture_dir: Path, old: bytes, new: bytes) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_minimal.eml").replace(old, new, 1)

    with pytest.raises(UnsupportedEmailError):
        _parse(raw)


def test_rejects_duplicate_summary_label(fixture_dir: Path) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_minimal.eml").replace(
        b"<tr><td>Subtotal</td></tr>",
        b"<tr><td>Subtotal</td></tr>\n<tr><td>Subtotal</td></tr>",
        1,
    )

    with pytest.raises(UnsupportedEmailError):
        _parse(raw)


def test_rejects_unreconciled_order_total(fixture_dir: Path) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_minimal.eml").replace(
        b"<tr><td>Total</td></tr>\n    <tr><td>S$14.00</td></tr>",
        b"<tr><td>Total</td></tr>\n    <tr><td>S$14.01</td></tr>",
        1,
    )

    with pytest.raises(UnsupportedEmailError, match="E_ORDER_TOTAL"):
        _parse(raw)


def test_rejects_conflicting_displayed_order_totals(fixture_dir: Path) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_minimal.eml").replace(
        b"<tr><td>Order Total</td></tr>\n    <tr><td>S$14.00</td></tr>",
        b"<tr><td>Order Total</td></tr>\n    <tr><td>S$99.00</td></tr>",
        1,
    )

    with pytest.raises(UnsupportedEmailError, match="E_ORDER_TOTAL: displayed totals disagree"):
        _parse(raw)


def test_rejects_unexpected_text_inside_item_rows(fixture_dir: Path) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_minimal.eml").replace(
        b"<tr><td>Example Paper Towels 2 Pack</td></tr>",
        b"<tr><td>Unexpected tracking text</td></tr>\n"
        b"    <tr><td>Example Paper Towels 2 Pack</td></tr>",
        1,
    )

    with pytest.raises(UnsupportedEmailError, match="E_ITEM"):
        _parse(raw)


def test_rejects_multiple_vendor_candidates(fixture_dir: Path) -> None:
    minimal = _fixture(fixture_dir, "fairprice_order_minimal.eml")
    adjusted = _fixture(fixture_dir, "fairprice_order_adjusted.eml")
    ambiguous = (
        b"From: Example <wrapper@example.invalid>\n"
        b"To: Inbox <inbox@example.invalid>\n"
        b"Date: Tue, 13 Jan 2026 09:00:00 +0800\n"
        b"Message-ID: <ambiguous@example.invalid>\n"
        b"Subject: Two attached orders\n"
        b"MIME-Version: 1.0\n"
        b'Content-Type: multipart/mixed; boundary="ambiguous"\n\n'
        b"--ambiguous\nContent-Type: message/rfc822\n\n"
        + minimal
        + b"\n--ambiguous\nContent-Type: message/rfc822\n\n"
        + adjusted
        + b"\n--ambiguous--\n"
    )

    with pytest.raises(UnsupportedEmailError, match="multiple FairPrice"):
        _parse(ambiguous)


def test_html_remote_resources_are_never_fetched(
    fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_network(*args, **kwargs):
        del args, kwargs
        raise AssertionError("parser attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)

    parsed = _parse(_fixture(fixture_dir, "fairprice_order_minimal.eml"))

    assert parsed.order.external_order_id == "EXAMPLE01"


def test_source_and_wrapper_dates_must_be_timezone_aware(fixture_dir: Path) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_minimal.eml").replace(
        b"Date: Sun, 11 Jan 2026 10:00:00 +0800",
        b"Date: Sun, 11 Jan 2026 10:00:00",
        1,
    )

    with pytest.raises(UnsupportedEmailError, match="E_HEADER_DATE"):
        _parse(raw)


def test_duplicate_identity_or_ordering_header_is_rejected(fixture_dir: Path) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_minimal.eml").replace(
        b"Date: Sun, 11 Jan 2026 10:00:00 +0800",
        b"Date: Sun, 11 Jan 2026 10:00:00 +0800\nDate: Sun, 11 Jan 2026 12:00:00 +0800",
        1,
    )

    with pytest.raises(UnsupportedEmailError, match="E_HEADER_DUPLICATE"):
        _parse(raw)


def test_malformed_hidden_html_cannot_expose_order_facts(fixture_dir: Path) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_minimal.eml").replace(
        b"<body>", b"<body><template></style>", 1
    )

    with pytest.raises(UnsupportedEmailError, match="E_HTML_BODY"):
        _parse(raw)


def test_included_tax_cannot_exceed_order_value(fixture_dir: Path) -> None:
    raw = _fixture(fixture_dir, "fairprice_order_adjusted.eml").replace(
        b"<tr><td>S$1.24</td></tr>", b"<tr><td>S$99.99</td></tr>", 1
    )

    with pytest.raises(UnsupportedEmailError, match="E_ORDER_TOTAL"):
        _parse(raw)


def test_money_parser_is_strict_and_bounded() -> None:
    assert parse_sgd_cents("S$1,234.50") == 123_450
    assert parse_sgd_cents("-SGD 2.00") == -200
    assert parse_sgd_cents("($2.00)") == -200
    for value in ("S$1e3", "S$NaN", "S$1.234", "(S$2.00", "S$1,00.00", "S$1000000.01"):
        with pytest.raises(ValueError):
            parse_sgd_cents(value)
