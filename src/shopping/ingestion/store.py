"""Transactional ingestion and read queries."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopping.ingestion.archive import ArchivedSource
from shopping.ingestion.models import (
    ImportResult,
    ParsedEmail,
    ParsedItem,
    ParsedOrder,
)
from shopping.purchases.normalization import (
    listing_key,
    normalize_text,
    package_size,
    provisional_product_key,
    utc_iso,
)
from shopping.storage.connection import connect_database, transaction


class NeedsReviewError(RuntimeError):
    """An import cannot safely replace current factual data automatically."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def revision_fingerprint(order: ParsedOrder, *, source_event: datetime) -> str:
    payload = {
        "version": 3,
        "retailer": order.retailer_slug,
        "retailer_country": order.retailer_country,
        "order_id": order.external_order_id,
        "revision_kind": order.revision_kind,
        "source_event_at": utc_iso(source_event),
        "ordered_at": utc_iso(order.ordered_at) if order.ordered_at else None,
        "delivery_at": utc_iso(order.delivery_at) if order.delivery_at else None,
        "currency": order.currency,
        "subtotal_cents": order.subtotal_cents,
        "discount_cents": order.discount_cents,
        "delivery_fee_cents": order.delivery_fee_cents,
        "service_fee_cents": order.service_fee_cents,
        "other_fee_cents": order.other_fee_cents,
        "tax_cents": order.tax_cents,
        "included_tax_cents": order.included_tax_cents,
        "total_cents": order.total_cents,
        "status": order.status,
        "items": [
            {
                "line_number": item.line_number,
                "name": normalize_text(item.name),
                "sku": normalize_text(item.external_sku) if item.external_sku else None,
                "quantity": str(item.quantity),
                "unit": normalize_text(item.unit),
                "unit_price_cents": item.unit_price_cents,
                "gross_cents": item.gross_cents,
                "discount_cents": item.discount_cents,
                "net_cents": item.net_cents,
            }
            for item in order.items
        ],
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def line_fingerprint(item: ParsedItem) -> str:
    payload = {
        "version": 1,
        "ordinal": item.line_number,
        "name": normalize_text(item.name),
        "sku": normalize_text(item.external_sku) if item.external_sku else None,
        "quantity": str(item.quantity),
        "unit": normalize_text(item.unit),
        "unit_price_cents": item.unit_price_cents,
        "gross_cents": item.gross_cents,
        "discount_cents": item.discount_cents,
        "net_cents": item.net_cents,
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def find_source_by_sha(database_path: Path, raw_sha256: str) -> sqlite3.Row | None:
    if not database_path.exists():
        return None
    connection = connect_database(database_path)
    try:
        return connection.execute(
            "SELECT id, parse_status FROM email_messages WHERE raw_sha256 = ?", (raw_sha256,)
        ).fetchone()
    except sqlite3.OperationalError as error:
        if "no such table" in str(error):
            return None
        raise
    finally:
        connection.close()


def _email_by_identity(
    connection: sqlite3.Connection,
    *,
    source_message_key: str,
    raw_sha256: str,
    gmail_message_id: str | None,
) -> sqlite3.Row | None:
    if gmail_message_id is not None:
        row = connection.execute(
            "SELECT * FROM email_messages WHERE gmail_message_id = ?",
            (gmail_message_id,),
        ).fetchone()
        if row is not None:
            if row["raw_sha256"] != raw_sha256:
                raise NeedsReviewError("Gmail message ID belongs to different raw bytes")
            return row
    row = connection.execute(
        "SELECT * FROM email_messages WHERE raw_sha256 = ?", (raw_sha256,)
    ).fetchone()
    if row is not None:
        return row
    row = connection.execute(
        "SELECT * FROM email_messages WHERE source_message_key = ?",
        (source_message_key,),
    ).fetchone()
    if row is not None and row["raw_sha256"] != raw_sha256:
        raise NeedsReviewError("source message key already belongs to different raw bytes")
    return row


def _attach_gmail_metadata(
    connection: sqlite3.Connection,
    *,
    email_id: int,
    gmail_message_id: str | None,
    gmail_thread_id: str | None,
    gmail_internal_at: str | None,
) -> None:
    if gmail_message_id is None:
        return
    current = connection.execute(
        "SELECT gmail_message_id FROM email_messages WHERE id = ?", (email_id,)
    ).fetchone()
    if current is None:
        raise RuntimeError("email source disappeared while attaching Gmail metadata")
    # Migration 001 intentionally models one Gmail acquisition per exact raw
    # message. If Gmail exposes identical bytes under a second ID, the raw source
    # still deduplicates safely; a later multi-account migration can retain every
    # acquisition locator if that case proves useful.
    if current["gmail_message_id"] not in {None, gmail_message_id}:
        return
    connection.execute(
        """
        UPDATE email_messages
        SET gmail_message_id = ?, gmail_thread_id = ?, gmail_internal_at = ?,
            fetched_at = ?
        WHERE id = ?
        """,
        (gmail_message_id, gmail_thread_id, gmail_internal_at, _utc_now(), email_id),
    )


def _insert_email(
    connection: sqlite3.Connection, parsed: ParsedEmail, archived: ArchivedSource
) -> sqlite3.Row:
    metadata = parsed.metadata
    now = _utc_now()
    gmail_internal_at = utc_iso(metadata.gmail_internal_at) if metadata.gmail_internal_at else None
    row = _email_by_identity(
        connection,
        source_message_key=metadata.source_message_key,
        raw_sha256=archived.sha256,
        gmail_message_id=metadata.gmail_message_id,
    )
    if row is not None:
        email_id = int(row["id"])
        _attach_gmail_metadata(
            connection,
            email_id=email_id,
            gmail_message_id=metadata.gmail_message_id,
            gmail_thread_id=metadata.gmail_thread_id,
            gmail_internal_at=gmail_internal_at,
        )
        if row["parse_status"] != "parsed":
            connection.execute(
                """
                UPDATE email_messages
                SET rfc822_message_id = ?, original_message_id = ?,
                    source_fingerprint = ?, sender = ?, recipient = ?, subject = ?,
                    received_at = ?, source_sent_at = ?, parser_version = ?, fetched_at = ?
                WHERE id = ?
                """,
                (
                    metadata.rfc822_message_id,
                    metadata.original_message_id,
                    metadata.source_fingerprint,
                    metadata.sender,
                    metadata.recipient,
                    metadata.subject,
                    utc_iso(metadata.received_at),
                    utc_iso(metadata.source_sent_at) if metadata.source_sent_at else None,
                    parsed.parser_version,
                    now,
                    email_id,
                ),
            )
        return connection.execute(
            "SELECT id, parse_status, raw_sha256 FROM email_messages WHERE id = ?",
            (email_id,),
        ).fetchone()

    try:
        connection.execute(
            """
            INSERT INTO email_messages (
                source_kind, source_message_key, gmail_message_id, gmail_thread_id,
                rfc822_message_id, original_message_id, source_fingerprint, sender,
                recipient, subject, received_at, gmail_internal_at, source_sent_at,
                raw_sha256, raw_path, parse_status, parser_version, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            ON CONFLICT(source_message_key) DO NOTHING
            """,
            (
                metadata.source_kind,
                metadata.source_message_key,
                metadata.gmail_message_id,
                metadata.gmail_thread_id,
                metadata.rfc822_message_id,
                metadata.original_message_id,
                metadata.source_fingerprint,
                metadata.sender,
                metadata.recipient,
                metadata.subject,
                utc_iso(metadata.received_at),
                gmail_internal_at,
                utc_iso(metadata.source_sent_at) if metadata.source_sent_at else None,
                archived.sha256,
                str(archived.path),
                parsed.parser_version,
                now,
            ),
        )
    except sqlite3.IntegrityError:
        # A concurrent import can win either the source-key, Gmail-ID, or raw-hash
        # uniqueness race. Re-resolve the winner and validate its raw identity.
        pass
    row = _email_by_identity(
        connection,
        source_message_key=metadata.source_message_key,
        raw_sha256=archived.sha256,
        gmail_message_id=metadata.gmail_message_id,
    )
    if row is None:
        raise RuntimeError("source row was not created")
    if row["raw_sha256"] != archived.sha256:
        raise NeedsReviewError("source message key already belongs to different raw bytes")
    return row


def _get_or_create_retailer(connection: sqlite3.Connection, parsed: ParsedEmail) -> int:
    now = _utc_now()
    order = parsed.order
    connection.execute(
        """
        INSERT INTO retailers (slug, name, country, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(slug) DO NOTHING
        """,
        (order.retailer_slug, order.retailer_name, order.retailer_country, now),
    )
    retailer = connection.execute(
        "SELECT id, name, country FROM retailers WHERE slug = ?", (order.retailer_slug,)
    ).fetchone()
    if retailer is None:
        raise RuntimeError("retailer row was not created")
    if (retailer["name"], retailer["country"]) != (
        order.retailer_name,
        order.retailer_country,
    ):
        raise NeedsReviewError("retailer slug conflicts with different identity metadata")
    return int(retailer["id"])


def _get_or_create_order(
    connection: sqlite3.Connection, *, retailer_id: int, external_order_id: str
) -> int:
    connection.execute(
        """
        INSERT INTO orders (retailer_id, external_order_id, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(retailer_id, external_order_id) DO NOTHING
        """,
        (retailer_id, external_order_id, _utc_now()),
    )
    return int(
        connection.execute(
            "SELECT id FROM orders WHERE retailer_id = ? AND external_order_id = ?",
            (retailer_id, external_order_id),
        ).fetchone()[0]
    )


def _get_or_create_listing(
    connection: sqlite3.Connection, *, retailer_id: int, retailer_slug: str, item: ParsedItem
) -> int:
    now = _utc_now()
    normalized_name = normalize_text(item.name)
    product_key = provisional_product_key(
        retailer_slug=retailer_slug,
        name=item.name,
        external_sku=item.external_sku,
    )
    size_quantity, size_unit = package_size(item.name)
    connection.execute(
        """
        INSERT INTO products (
            canonical_key, canonical_name, normalized_name, package_quantity,
            package_unit, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(canonical_key) DO UPDATE SET updated_at = excluded.updated_at
        """,
        (product_key, item.name, normalized_name, size_quantity, size_unit, now, now),
    )
    product_id = int(
        connection.execute(
            "SELECT id FROM products WHERE canonical_key = ?", (product_key,)
        ).fetchone()[0]
    )
    item_listing_key = listing_key(
        retailer_slug=retailer_slug, name=item.name, external_sku=item.external_sku
    )
    connection.execute(
        """
        INSERT INTO retailer_products (
            retailer_id, external_sku, listing_key, product_id, latest_name,
            latest_size_text, match_status, match_method, match_confidence,
            first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'provisional', 'parser', 1.0, ?, ?)
        ON CONFLICT(retailer_id, listing_key) DO NOTHING
        """,
        (
            retailer_id,
            item.external_sku,
            item_listing_key,
            product_id,
            item.name,
            f"{size_quantity:g}{size_unit}" if size_quantity is not None and size_unit else None,
            now,
            now,
        ),
    )
    row = connection.execute(
        """
        SELECT id, product_id FROM retailer_products
        WHERE retailer_id = ? AND listing_key = ?
        """,
        (retailer_id, item_listing_key),
    ).fetchone()
    if row["product_id"] != product_id:
        raise NeedsReviewError("retailer listing maps to a different canonical product")
    connection.execute(
        "UPDATE retailer_products SET latest_name = ?, last_seen_at = ? WHERE id = ?",
        (item.name, now, row["id"]),
    )
    return int(row["id"])


_REVISION_RANK = {"confirmation": 1, "amendment": 2, "receipt": 3, "refund": 4}


def persist_parsed_email(
    database_path: Path, parsed: ParsedEmail, archived: ArchivedSource
) -> ImportResult:
    connection = connect_database(database_path)
    try:
        with transaction(connection):
            email_row = _insert_email(connection, parsed, archived)
            email_id = int(email_row["id"])
            if email_row["parse_status"] == "parsed":
                source = connection.execute(
                    """
                    SELECT ors.order_revision_id, rev.order_id
                    FROM order_revision_sources ors
                    JOIN order_revisions rev ON rev.id = ors.order_revision_id
                    WHERE ors.email_message_id = ?
                    ORDER BY ors.order_revision_id DESC LIMIT 1
                    """,
                    (email_id,),
                ).fetchone()
                return ImportResult(
                    outcome="duplicate_source",
                    email_message_id=email_id,
                    order_id=int(source["order_id"]) if source else None,
                    order_revision_id=int(source["order_revision_id"]) if source else None,
                    archived_path=str(archived.path),
                )

            retailer_id = _get_or_create_retailer(connection, parsed)
            order_id = _get_or_create_order(
                connection,
                retailer_id=retailer_id,
                external_order_id=parsed.order.external_order_id,
            )
            source_event = parsed.metadata.source_sent_at or parsed.metadata.received_at
            source_event_at = utc_iso(source_event)
            fingerprint = revision_fingerprint(parsed.order, source_event=source_event)
            existing_revision = connection.execute(
                """
                SELECT id FROM order_revisions
                WHERE order_id = ? AND revision_fingerprint = ?
                """,
                (order_id, fingerprint),
            ).fetchone()
            now = _utc_now()
            if existing_revision is not None:
                revision_id = int(existing_revision["id"])
                connection.execute(
                    """
                    INSERT OR IGNORE INTO order_revision_sources
                        (order_revision_id, email_message_id, linked_at)
                    VALUES (?, ?, ?)
                    """,
                    (revision_id, email_id, now),
                )
                connection.execute(
                    """
                    UPDATE email_messages
                    SET parse_status = 'parsed', parser_version = ?, parse_error = NULL,
                        parsed_at = ?
                    WHERE id = ?
                    """,
                    (parsed.parser_version, now, email_id),
                )
                return ImportResult(
                    outcome="duplicate_revision",
                    email_message_id=email_id,
                    order_id=order_id,
                    order_revision_id=revision_id,
                    archived_path=str(archived.path),
                )

            current = connection.execute(
                """
                SELECT id, revision_kind, source_event_at FROM order_revisions
                WHERE order_id = ? AND is_current = 1
                """,
                (order_id,),
            ).fetchone()
            should_be_current = current is None
            if current is not None:
                current_event = datetime.fromisoformat(str(current["source_event_at"]))
                if source_event > current_event:
                    should_be_current = True
                elif source_event < current_event:
                    should_be_current = False
                elif (
                    _REVISION_RANK[parsed.order.revision_kind]
                    > _REVISION_RANK[current["revision_kind"]]
                ):
                    should_be_current = True
                else:
                    raise NeedsReviewError(
                        "revision has the same source timestamp without higher precedence"
                    )
            revision_number = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(revision_number), 0) + 1
                    FROM order_revisions WHERE order_id = ?
                    """,
                    (order_id,),
                ).fetchone()[0]
            )
            if current is not None and should_be_current:
                connection.execute(
                    "UPDATE order_revisions SET is_current = 0 WHERE id = ?", (current["id"],)
                )
            cursor = connection.execute(
                """
                INSERT INTO order_revisions (
                    order_id, email_message_id, revision_number, revision_kind,
                    revision_fingerprint, parser_version, source_event_at,
                    ordered_at, delivery_at,
                    currency, subtotal_cents, discount_cents, delivery_fee_cents,
                    service_fee_cents, other_fee_cents, tax_cents,
                    included_tax_cents, total_cents, status, is_current, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    email_id,
                    revision_number,
                    parsed.order.revision_kind,
                    fingerprint,
                    parsed.parser_version,
                    source_event_at,
                    utc_iso(parsed.order.ordered_at) if parsed.order.ordered_at else None,
                    utc_iso(parsed.order.delivery_at) if parsed.order.delivery_at else None,
                    parsed.order.currency,
                    parsed.order.subtotal_cents,
                    parsed.order.discount_cents,
                    parsed.order.delivery_fee_cents,
                    parsed.order.service_fee_cents,
                    parsed.order.other_fee_cents,
                    parsed.order.tax_cents,
                    parsed.order.included_tax_cents,
                    parsed.order.total_cents,
                    parsed.order.status,
                    int(should_be_current),
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("revision insert did not return an identifier")
            revision_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO order_revision_sources
                    (order_revision_id, email_message_id, linked_at)
                VALUES (?, ?, ?)
                """,
                (revision_id, email_id, now),
            )
            for item in parsed.order.items:
                retailer_product_id = _get_or_create_listing(
                    connection,
                    retailer_id=retailer_id,
                    retailer_slug=parsed.order.retailer_slug,
                    item=item,
                )
                connection.execute(
                    """
                    INSERT INTO order_items (
                        order_revision_id, line_number, line_fingerprint,
                        retailer_product_id, raw_name, quantity, unit,
                        unit_price_cents, gross_cents, discount_cents, net_cents,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        revision_id,
                        item.line_number,
                        line_fingerprint(item),
                        retailer_product_id,
                        item.name,
                        float(item.quantity),
                        item.unit,
                        item.unit_price_cents,
                        item.gross_cents,
                        item.discount_cents,
                        item.net_cents,
                        now,
                    ),
                )
            connection.execute(
                """
                UPDATE email_messages
                SET parse_status = 'parsed', parser_version = ?, parse_error = NULL,
                    parsed_at = ?
                WHERE id = ?
                """,
                (parsed.parser_version, now, email_id),
            )
            return ImportResult(
                outcome="imported",
                email_message_id=email_id,
                order_id=order_id,
                order_revision_id=revision_id,
                archived_path=str(archived.path),
            )
    finally:
        connection.close()


def record_failed_source(
    database_path: Path,
    archived: ArchivedSource,
    *,
    source_message_key: str,
    sender: str,
    recipient: str | None,
    subject: str,
    received_at: datetime,
    error: str,
    needs_review: bool = False,
    source_kind: str = "manual",
    gmail_message_id: str | None = None,
    gmail_thread_id: str | None = None,
    gmail_internal_at: datetime | None = None,
) -> int:
    if source_kind not in {"manual", "gmail"}:
        raise ValueError("source kind must be 'manual' or 'gmail'")
    if source_kind == "gmail" and (
        gmail_message_id is None or gmail_thread_id is None or gmail_internal_at is None
    ):
        raise ValueError("Gmail failures require message, thread, and internal timestamp metadata")
    now = _utc_now()
    status = "needs_review" if needs_review else "failed"
    gmail_internal_text = utc_iso(gmail_internal_at) if gmail_internal_at else None
    connection = connect_database(database_path)
    try:
        with transaction(connection):
            row = _email_by_identity(
                connection,
                source_message_key=source_message_key,
                raw_sha256=archived.sha256,
                gmail_message_id=gmail_message_id,
            )
            if row is not None:
                email_id = int(row["id"])
                _attach_gmail_metadata(
                    connection,
                    email_id=email_id,
                    gmail_message_id=gmail_message_id,
                    gmail_thread_id=gmail_thread_id,
                    gmail_internal_at=gmail_internal_text,
                )
                connection.execute(
                    """
                    UPDATE email_messages
                    SET sender = ?, recipient = ?, subject = ?, received_at = ?,
                        parse_status = ?, parse_error = ?, fetched_at = ?
                    WHERE id = ? AND parse_status <> 'parsed'
                    """,
                    (
                        sender,
                        recipient,
                        subject,
                        utc_iso(received_at),
                        status,
                        error[:1000],
                        now,
                        email_id,
                    ),
                )
                return email_id

            try:
                cursor = connection.execute(
                    """
                    INSERT INTO email_messages (
                        source_kind, source_message_key, gmail_message_id,
                        gmail_thread_id, source_fingerprint, sender, recipient,
                        subject, received_at, gmail_internal_at, raw_sha256,
                        raw_path, parse_status, parse_error, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_kind,
                        source_message_key,
                        gmail_message_id,
                        gmail_thread_id,
                        archived.sha256,
                        sender,
                        recipient,
                        subject,
                        utc_iso(received_at),
                        gmail_internal_text,
                        archived.sha256,
                        str(archived.path),
                        status,
                        error[:1000],
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                row = _email_by_identity(
                    connection,
                    source_message_key=source_message_key,
                    raw_sha256=archived.sha256,
                    gmail_message_id=gmail_message_id,
                )
                if row is None:
                    raise
                return int(row["id"])
            if cursor.lastrowid is None:
                raise RuntimeError("failed source insert did not return an identifier")
            return int(cursor.lastrowid)
    finally:
        connection.close()
