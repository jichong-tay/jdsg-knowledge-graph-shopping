"""Strict values exchanged between parsing and persistence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EmailMetadata(StrictModel):
    source_kind: Literal["manual", "gmail"] = "manual"
    source_message_key: str
    gmail_message_id: str | None = None
    gmail_thread_id: str | None = None
    rfc822_message_id: str | None = None
    original_message_id: str | None = None
    source_fingerprint: str
    sender: str
    recipient: str | None = None
    subject: str
    received_at: datetime
    gmail_internal_at: datetime | None = None
    source_sent_at: datetime | None = None

    @field_validator("received_at", "gmail_internal_at", "source_sent_at")
    @classmethod
    def require_email_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("email timestamps must be timezone-aware")
        return value


class GmailSource(StrictModel):
    account_key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    message_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    thread_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    internal_at: datetime

    @field_validator("internal_at")
    @classmethod
    def require_internal_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Gmail internal timestamp must be timezone-aware")
        return value

    @property
    def source_message_key(self) -> str:
        return f"gmail:{self.account_key}:{self.message_id}"


class GmailSyncState(StrictModel):
    account_key: str
    gmail_history_id: str | None = None
    scan_watermark_at: datetime
    overlap_seconds: int = Field(ge=0)
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    updated_at: datetime


class ParsedItem(StrictModel):
    line_number: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=500)
    external_sku: str | None = Field(default=None, max_length=100)
    quantity: Decimal
    unit: str = Field(default="item", min_length=1, max_length=30)
    unit_price_cents: int = Field(ge=0)
    gross_cents: int = Field(ge=0)
    discount_cents: int = Field(default=0, ge=0)
    net_cents: int = Field(ge=0)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > 100_000:
            raise ValueError("quantity must be finite and between 0 and 100000")
        return value.normalize()

    @model_validator(mode="after")
    def reconcile_line(self) -> ParsedItem:
        if self.discount_cents > self.gross_cents:
            raise ValueError("line discount cannot exceed gross amount")
        if self.gross_cents - self.discount_cents != self.net_cents:
            raise ValueError("line gross minus discount must equal net amount")
        return self


class ParsedOrder(StrictModel):
    retailer_slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    retailer_name: str = Field(min_length=1, max_length=200)
    retailer_country: str = Field(pattern=r"^[A-Z]{2}$")
    external_order_id: str = Field(min_length=1, max_length=100)
    revision_kind: Literal["confirmation", "amendment", "receipt", "refund"]
    ordered_at: datetime | None
    delivery_at: datetime | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    subtotal_cents: int = Field(ge=0)
    discount_cents: int = Field(default=0, ge=0)
    delivery_fee_cents: int = Field(default=0, ge=0)
    service_fee_cents: int = Field(default=0, ge=0)
    other_fee_cents: int = Field(default=0, ge=0)
    tax_cents: int = Field(default=0, ge=0)
    included_tax_cents: int = Field(default=0, ge=0)
    total_cents: int = Field(ge=0)
    status: Literal["placed", "completed", "cancelled", "refunded", "unknown"]
    items: tuple[ParsedItem, ...] = Field(min_length=1)

    @field_validator("ordered_at", "delivery_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def reconcile_totals(self) -> ParsedOrder:
        line_total = sum(item.net_cents for item in self.items)
        if line_total != self.subtotal_cents:
            raise ValueError(
                f"line totals ({line_total}) do not match subtotal ({self.subtotal_cents})"
            )
        expected = (
            self.subtotal_cents
            - self.discount_cents
            + self.delivery_fee_cents
            + self.service_fee_cents
            + self.other_fee_cents
            + self.tax_cents
        )
        if expected != self.total_cents:
            raise ValueError(
                f"summary amounts ({expected}) do not match total ({self.total_cents})"
            )
        pre_redemption_basis = self.total_cents + self.discount_cents
        if self.included_tax_cents > pre_redemption_basis:
            raise ValueError("included tax cannot exceed the pre-redemption order value")
        return self


class ParsedEmail(StrictModel):
    metadata: EmailMetadata
    order: ParsedOrder
    parser_version: str


class ImportResult(StrictModel):
    outcome: Literal["imported", "duplicate_source", "duplicate_revision", "needs_review"]
    email_message_id: int
    order_id: int | None = None
    order_revision_id: int | None = None
    archived_path: str
