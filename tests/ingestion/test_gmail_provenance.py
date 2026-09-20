from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from shopping.ingestion.gmail.provenance import (
    PROVENANCE_VERIFIER_VERSION,
    GmailProvenanceResult,
    verify_gmail_provenance,
)


def _email(
    *,
    sender: str = "orders@fairprice.com.sg",
    authentication_results: tuple[str, ...] = (
        "mx.google.com; dkim=pass header.i=@fairprice.com.sg "
        "header.s=example header.b=opaque; dmarc=pass header.from=fairprice.com.sg",
    ),
) -> bytes:
    headers = [
        f"From: Vendor <{sender}>",
        "To: Shopper <shopper@example.invalid>",
        "Subject: Synthetic receipt",
        "Date: Tue, 11 Aug 2026 12:00:00 +0800",
        "Message-ID: <provenance-test@example.invalid>",
        *(f"Authentication-Results: {value}" for value in authentication_results),
        "Content-Type: text/plain; charset=utf-8",
    ]
    return ("\r\n".join(headers) + "\r\n\r\nSynthetic body.\r\n").encode()


def test_accepts_aligned_google_dkim_for_vendor_subdomain() -> None:
    raw = _email(
        sender="orders@mail.fairprice.com.sg",
        authentication_results=(
            "mx.google.com; dkim=pass header.i=mailer@news.fairprice.com.sg "
            "header.d=mail.fairprice.com.sg",
        ),
    )

    result = verify_gmail_provenance(raw)

    assert result == GmailProvenanceResult(
        verified=True,
        method="gmail_authentication_results_dkim",
        code="verified_aligned_dkim",
        version=PROVENANCE_VERIFIER_VERSION,
    )


def test_accepts_aligned_google_dmarc_when_dkim_does_not_pass() -> None:
    raw = _email(
        authentication_results=(
            "mail-ua1-f47.google.com; spf=pass smtp.mailfrom=mailer.example.invalid; "
            "dkim=fail header.d=fairprice.com.sg; "
            "dmarc=pass (p=reject sp=reject dis=none) header.from=fairprice.com.sg",
        )
    )

    result = verify_gmail_provenance(raw)

    assert result.verified is True
    assert result.method == "gmail_authentication_results_dmarc"
    assert result.code == "verified_aligned_dmarc"


@pytest.mark.parametrize(
    ("authentication_results", "expected_code"),
    [
        ((), "authentication_results_missing"),
        (
            ("mail.attacker.invalid; dkim=pass header.d=fairprice.com.sg",),
            "authentication_results_not_google",
        ),
        (
            ("mx.google.com.attacker.invalid; dkim=pass header.d=fairprice.com.sg",),
            "authentication_results_not_google",
        ),
        (("mx.google.com; dkim=fail header.d=fairprice.com.sg",), "authentication_not_passed"),
        (
            ("mx.google.com; dmarc=pass header.from=attacker.invalid",),
            "authentication_identity_misaligned",
        ),
        (
            ("mx.google.com; dkim=pass header.d=fairprice.com.sg header.d=attacker.invalid",),
            "authentication_identity_misaligned",
        ),
        (
            ('mx.google.com; dkim=pass reason="header.d=fairprice.com.sg"',),
            "malformed_authentication_results",
        ),
        (
            ("mx.google.com; dmarc=pass (header.from=fairprice.com.sg)",),
            "authentication_identity_misaligned",
        ),
    ],
)
def test_rejects_missing_failed_misaligned_or_ambiguous_authentication(
    authentication_results: tuple[str, ...],
    expected_code: str,
) -> None:
    result = verify_gmail_provenance(_email(authentication_results=authentication_results))

    assert result.verified is False
    assert result.method == "none"
    assert result.code == expected_code


@pytest.mark.parametrize(
    "authentication_results",
    [
        (
            "mx.google.com; dkim=pass header.d=fairprice.com.sg",
            "attacker.invalid; dkim=pass header.d=fairprice.com.sg",
        ),
        (
            "attacker.invalid; dkim=pass header.d=fairprice.com.sg",
            "mx.google.com; dkim=pass header.d=fairprice.com.sg",
        ),
    ],
)
def test_rejects_inner_authentication_results_in_either_position(
    authentication_results: tuple[str, ...],
) -> None:
    result = verify_gmail_provenance(_email(authentication_results=authentication_results))

    assert result == GmailProvenanceResult(
        verified=False,
        method="none",
        code="multiple_authentication_results",
    )


def test_rejects_non_vendor_sender_even_with_aligned_claim() -> None:
    result = verify_gmail_provenance(_email(sender="attacker@example.invalid"))

    assert result.verified is False
    assert result.code == "sender_domain_not_allowed"


def test_synthetic_vendor_domain_requires_explicit_fixture_flag() -> None:
    raw = _email(
        sender="orders@fairprice.example.invalid",
        authentication_results=("mx.google.com; dkim=pass header.d=fairprice.example.invalid",),
    )

    rejected = verify_gmail_provenance(raw)
    accepted = verify_gmail_provenance(raw, allow_synthetic_fixtures=True)

    assert rejected.code == "synthetic_fixture_not_allowed"
    assert accepted.verified is True
    assert accepted.code == "verified_aligned_dkim"


@pytest.mark.parametrize(
    "raw",
    [
        b" continued-without-header\r\n\r\nbody",
        b"From: orders@fairprice.com.sg\r\nAuthentication-Results: mx.google.com; "
        b"dkim=pass header.d=fairprice.com.sg\r\nbody-without-header-separator",
        b"",
    ],
)
def test_malformed_mime_fails_closed(raw: bytes) -> None:
    result = verify_gmail_provenance(raw)

    assert result.verified is False
    assert result.code == "malformed_mime"


def test_duplicate_from_header_fails_closed() -> None:
    raw = _email().replace(
        b"From: Vendor <orders@fairprice.com.sg>\r\n",
        b"From: Vendor <orders@fairprice.com.sg>\r\nFrom: Attacker <attacker@example.invalid>\r\n",
        1,
    )

    result = verify_gmail_provenance(raw)

    assert result.verified is False
    assert result.code == "invalid_from_header"


def test_result_is_immutable_and_does_not_expose_header_values() -> None:
    secret_marker = "secret-authentication-detail"
    result = verify_gmail_provenance(
        _email(
            authentication_results=(
                f"mx.google.com; dkim=fail reason={secret_marker} header.d=fairprice.com.sg",
            )
        )
    )

    with pytest.raises(FrozenInstanceError):
        result.code = secret_marker  # type: ignore[misc]
    assert secret_marker not in repr(result)


def test_nested_forward_is_not_treated_as_direct_vendor_provenance() -> None:
    nested = _email()
    raw = (
        b"From: Shopper <shopper@example.invalid>\r\n"
        b"To: Inbox <inbox@example.invalid>\r\n"
        b"Subject: Fwd: receipt\r\n"
        b"Content-Type: message/rfc822\r\n\r\n" + nested
    )

    result = verify_gmail_provenance(raw)

    assert result.verified is False
    assert result.code == "sender_domain_not_allowed"
