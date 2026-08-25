"""Fail-closed provenance checks for messages fetched through the Gmail API.

The caller must supply the exact RFC 822 bytes returned by an authenticated Gmail
API request.  An ``Authentication-Results`` header is not trustworthy when read
from an arbitrary local file because a sender can create that header themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email import policy
from email.errors import MessageError
from email.headerregistry import AddressHeader
from email.message import EmailMessage
from email.parser import BytesParser
from typing import cast

PROVENANCE_VERIFIER_VERSION = "gmail-authentication-results-v1"

_PRODUCTION_VENDOR_DOMAIN = "fairprice.com.sg"
_SYNTHETIC_VENDOR_DOMAIN = "fairprice.example.invalid"
_MAX_EMAIL_BYTES = 20 * 1024 * 1024
_DNS_NAME = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
_AUTH_PROPERTY = re.compile(
    r"(?P<key>[a-z][a-z0-9_.-]*)\s*=\s*(?P<value>[^\s=]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class GmailProvenanceResult:
    """A non-sensitive, persistable result from the provenance verifier."""

    verified: bool
    method: str
    code: str
    version: str = PROVENANCE_VERIFIER_VERSION


def _result(*, verified: bool, method: str, code: str) -> GmailProvenanceResult:
    return GmailProvenanceResult(verified=verified, method=method, code=code)


def _failure(code: str) -> GmailProvenanceResult:
    return _result(verified=False, method="none", code=code)


def _normalize_domain(value: str) -> str | None:
    normalized = value.strip().removesuffix(".").casefold()
    if not normalized.isascii() or _DNS_NAME.fullmatch(normalized) is None:
        return None
    return normalized


def _is_same_or_subdomain(candidate: str, base: str) -> bool:
    return candidate == base or candidate.endswith(f".{base}")


def _vendor_domain(
    sender_domain: str,
    *,
    allow_synthetic_fixtures: bool,
) -> tuple[str | None, str | None]:
    if _is_same_or_subdomain(sender_domain, _PRODUCTION_VENDOR_DOMAIN):
        return _PRODUCTION_VENDOR_DOMAIN, None
    if _is_same_or_subdomain(sender_domain, _SYNTHETIC_VENDOR_DOMAIN):
        if allow_synthetic_fixtures:
            return _SYNTHETIC_VENDOR_DOMAIN, None
        return None, "synthetic_fixture_not_allowed"
    return None, "sender_domain_not_allowed"


def _from_domain(message: EmailMessage) -> tuple[str | None, str | None]:
    headers = cast(list[object], message.get_all("From", []) or [])
    if len(headers) != 1:
        return None, "invalid_from_header"
    header = headers[0]
    if (
        not isinstance(header, AddressHeader)
        or getattr(header, "defects", ())
        or len(header.addresses) != 1
    ):
        return None, "invalid_from_header"
    address = header.addresses[0]
    if not address.username or not address.domain:
        return None, "invalid_from_header"
    domain = _normalize_domain(address.domain)
    if domain is None:
        return None, "invalid_from_header"
    return domain, None


def _split_sections(value: str) -> tuple[str, ...] | None:
    """Split on semicolons while removing comments that must not authenticate."""

    sections: list[str] = []
    current: list[str] = []
    comment_depth = 0
    escaped = False
    quoted = False

    for character in value:
        if escaped:
            # Preserve token separation but never preserve content hidden in a
            # comment or quoted string.
            if comment_depth or quoted:
                current.append(" ")
            else:
                current.append(character)
            escaped = False
            continue
        if character == "\\":
            if not comment_depth and not quoted:
                return None
            escaped = True
            continue
        if quoted:
            if character == '"':
                quoted = False
            else:
                current.append(" ")
            continue
        if comment_depth:
            if character == "(":
                comment_depth += 1
            elif character == ")":
                comment_depth -= 1
            else:
                current.append(" ")
            continue
        if character == '"':
            quoted = True
            current.append(" ")
        elif character == "(":
            comment_depth = 1
            current.append(" ")
        elif character == ")":
            return None
        elif character == ";":
            sections.append("".join(current).strip())
            current = []
        else:
            current.append(character)

    if escaped or quoted or comment_depth:
        return None
    sections.append("".join(current).strip())
    return tuple(sections)


def _authserv_is_google(value: str) -> bool:
    tokens = value.casefold().split()
    if len(tokens) not in {1, 2} or (len(tokens) == 2 and not tokens[1].isdigit()):
        return False
    domain = _normalize_domain(tokens[0])
    return domain is not None and (domain == "mx.google.com" or domain.endswith(".google.com"))


def _parse_properties(section: str) -> dict[str, tuple[str, ...]] | None:
    properties: dict[str, list[str]] = {}
    position = 0
    for match in _AUTH_PROPERTY.finditer(section):
        if section[position : match.start()].strip():
            return None
        key = match.group("key").casefold()
        properties.setdefault(key, []).append(match.group("value").casefold())
        position = match.end()
    if section[position:].strip() or not properties:
        return None
    return {key: tuple(values) for key, values in properties.items()}


def _single_domain_property(
    properties: dict[str, tuple[str, ...]],
    name: str,
    *,
    identity: bool = False,
) -> str | None:
    values = properties.get(name, ())
    if len(values) != 1:
        return None
    value = values[0]
    if identity:
        if value.count("@") != 1:
            return None
        value = value.rsplit("@", maxsplit=1)[1]
    return _normalize_domain(value)


def _aligned_dkim(
    properties: dict[str, tuple[str, ...]],
    vendor_domain: str,
) -> bool:
    if properties.get("dkim") != ("pass",):
        return False
    if len(properties.get("header.d", ())) > 1 or len(properties.get("header.i", ())) > 1:
        return False
    candidates = (
        _single_domain_property(properties, "header.d"),
        _single_domain_property(properties, "header.i", identity=True),
    )
    return any(
        domain is not None and _is_same_or_subdomain(domain, vendor_domain) for domain in candidates
    )


def _aligned_dmarc(
    properties: dict[str, tuple[str, ...]],
    vendor_domain: str,
) -> bool:
    if properties.get("dmarc") != ("pass",):
        return False
    domain = _single_domain_property(properties, "header.from")
    return domain is not None and _is_same_or_subdomain(domain, vendor_domain)


def verify_gmail_provenance(
    raw_email: bytes,
    *,
    allow_synthetic_fixtures: bool = False,
) -> GmailProvenanceResult:
    """Verify conservative direct-delivery provenance for a Gmail API message.

    Results contain only stable codes; raw sender and authentication header values
    are deliberately never returned. Multiple ``Authentication-Results`` headers
    fail closed because forwarded-message header behavior has not yet been validated
    against this project's real mailbox.
    """

    if not isinstance(raw_email, bytes) or not raw_email or len(raw_email) > _MAX_EMAIL_BYTES:
        return _failure("malformed_mime")

    try:
        parser_policy = policy.default.clone(raise_on_defect=True)
        message = BytesParser(policy=parser_policy).parsebytes(raw_email)
        if message.defects:
            return _failure("malformed_mime")
        sender_domain, sender_error = _from_domain(message)
    except MessageError, TypeError, UnicodeError, ValueError:
        return _failure("malformed_mime")

    if sender_error is not None or sender_domain is None:
        return _failure(sender_error or "invalid_from_header")
    vendor_domain, vendor_error = _vendor_domain(
        sender_domain,
        allow_synthetic_fixtures=allow_synthetic_fixtures,
    )
    if vendor_error is not None or vendor_domain is None:
        return _failure(vendor_error or "sender_domain_not_allowed")

    try:
        auth_headers = message.get_all("Authentication-Results", []) or []
        if not auth_headers:
            return _failure("authentication_results_missing")
        if len(auth_headers) != 1:
            return _failure("multiple_authentication_results")
        auth_header = auth_headers[0]
        defects = getattr(auth_header, "defects", ())
        if defects:
            return _failure("malformed_authentication_results")
        sections = _split_sections(str(auth_header))
    except MessageError, TypeError, UnicodeError, ValueError:
        return _failure("malformed_authentication_results")

    if sections is None or len(sections) < 2 or not _authserv_is_google(sections[0]):
        if sections is not None and sections and not _authserv_is_google(sections[0]):
            return _failure("authentication_results_not_google")
        return _failure("malformed_authentication_results")

    parsed_sections: list[dict[str, tuple[str, ...]]] = []
    for section in sections[1:]:
        if not section:
            return _failure("malformed_authentication_results")
        properties = _parse_properties(section)
        if properties is None:
            return _failure("malformed_authentication_results")
        parsed_sections.append(properties)

    if any(_aligned_dkim(properties, vendor_domain) for properties in parsed_sections):
        return _result(
            verified=True,
            method="gmail_authentication_results_dkim",
            code="verified_aligned_dkim",
        )
    if any(_aligned_dmarc(properties, vendor_domain) for properties in parsed_sections):
        return _result(
            verified=True,
            method="gmail_authentication_results_dmarc",
            code="verified_aligned_dmarc",
        )

    passed = any(
        properties.get(method) == ("pass",)
        for properties in parsed_sections
        for method in ("dkim", "dmarc")
    )
    return _failure("authentication_identity_misaligned" if passed else "authentication_not_passed")


__all__ = [
    "PROVENANCE_VERIFIER_VERSION",
    "GmailProvenanceResult",
    "verify_gmail_provenance",
]
