"""Deterministic vendor email adapters.

Import parser entry points from this module so a future dispatcher can keep
vendor-specific details behind one package boundary.
"""

from app.email.parsers.base import UnsupportedEmailError
from app.email.parsers.fairprice import (
    PRODUCTION_FAIRPRICE_DOMAINS,
    parse_fairprice_email,
)
from app.models import ParsedEmail

_SYNTHETIC_FAIRPRICE_DOMAIN = "fairprice.example.invalid"


def parse_order_email(
    raw: bytes,
    *,
    source_message_key: str | None = None,
    allow_synthetic_fixtures: bool = False,
) -> ParsedEmail:
    """Dispatch an order email to a supported deterministic vendor adapter.

    The reserved test domain is deliberately opt-in and never enabled by the
    production default.
    """

    domains = PRODUCTION_FAIRPRICE_DOMAINS
    if allow_synthetic_fixtures:
        domains = domains | {_SYNTHETIC_FAIRPRICE_DOMAIN}
    return parse_fairprice_email(
        raw,
        source_message_key=source_message_key,
        allowed_sender_domains=frozenset(domains),
    )


__all__ = ["UnsupportedEmailError", "parse_fairprice_email", "parse_order_email"]
