"""Deterministic normalization helpers."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u2019", "'").replace("\u2013", "-").replace("\u2014", "-")
    return " ".join(value.casefold().split())


def listing_key(*, retailer_slug: str, name: str, external_sku: str | None) -> str:
    if external_sku:
        return f"sku:{normalize_text(external_sku)}"
    source = f"listing:v1:{retailer_slug}:{normalize_text(name)}"
    return f"name:v1:{sha256(source.encode()).hexdigest()}"


def provisional_product_key(*, retailer_slug: str, name: str, external_sku: str | None) -> str:
    identity = listing_key(
        retailer_slug=retailer_slug,
        name=name,
        external_sku=external_sku,
    )
    digest = sha256(f"provisional-product:v1:{retailer_slug}:{identity}".encode()).hexdigest()
    return f"provisional:{digest}"


def utc_iso(value: datetime) -> str:
    if value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds")


def package_size(name: str) -> tuple[float | None, str | None]:
    match = re.search(r"(?<!\w)(\d+(?:\.\d+)?)\s*(ml|l|g|kg|pcs?|pack)\b", name, re.I)
    if match is None:
        return None, None
    return float(Decimal(match.group(1))), match.group(2).lower()
