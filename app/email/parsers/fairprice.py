"""Deterministic adapter for supported FairPrice HTML order acknowledgements."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from email import policy
from email.errors import (
    CloseBoundaryNotFoundDefect,
    FirstHeaderLineIsContinuationDefect,
    MessageDefect,
    MisplacedEnvelopeHeaderDefect,
    MissingHeaderBodySeparatorDefect,
    MultipartInvariantViolationDefect,
    NoBoundaryInMultipartDefect,
    StartBoundaryNotFoundDefect,
    UndecodableBytesDefect,
)
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import ClassVar
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.email.parsers.base import UnsupportedEmailError
from app.models import EmailMetadata, ParsedEmail, ParsedItem, ParsedOrder

PARSER_VERSION = "fairprice-html-order-v1"
PRODUCTION_FAIRPRICE_DOMAINS = frozenset({"fairprice.com.sg"})
_SINGAPORE = ZoneInfo("Asia/Singapore")
_MAX_EMAIL_BYTES = 20 * 1024 * 1024
_MAX_BODY_CHARACTERS = 2 * 1024 * 1024
_MAX_MONEY_CENTS = 100_000_000

_SUBJECT = re.compile(
    r"^Thank you for your order (?P<order_id>[A-Z0-9][A-Z0-9_-]{1,99})$",
    re.IGNORECASE,
)
_ORDER_ID = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,99}$", re.IGNORECASE)
_ITEM_COUNT = re.compile(r"^(?P<count>[1-9]\d{0,3}) item\(s\)$", re.IGNORECASE)
_QUANTITY = re.compile(r"^(?:0|[1-9]\d{0,4})(?:\.\d{1,3})?$")
_DELIVERY_SLOT = re.compile(
    r"^(?P<start>\d{1,2}(?::\d{2})?\s*(?:am|pm))\s*"
    r"(?:-|\N{EN DASH}|\N{EM DASH}|to)\s*"
    r"(?P<end>\d{1,2}(?::\d{2})?\s*(?:am|pm))$",
    re.IGNORECASE,
)
_INLINE_MONEY = re.compile(
    r"(?<![\w$])(?P<value>(?:\(\s*)?(?:-\s*)?(?:SGD|S\$|\$)\s*"
    r"(?:\d{1,3}(?:,\d{3})+|\d{1,7})(?:\.\d{1,2})?(?:\s*\))?)",
    re.IGNORECASE,
)
_SGD_MONEY = re.compile(
    r"^\s*(?P<open>\()?\s*(?P<sign>-)?\s*(?:SGD|S\$|\$)\s*"
    r"(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d{1,7})(?:\.\d{1,2})?)"
    r"\s*(?P<close>\))?\s*$",
    re.IGNORECASE,
)


def parse_sgd_cents(value: str) -> int:
    """Parse the SGD forms accepted by this vendor adapter."""

    cleaned = unicodedata.normalize("NFKC", value)
    match = _SGD_MONEY.fullmatch(cleaned)
    if match is None:
        raise ValueError("invalid SGD money value")
    parenthesized = match.group("open") is not None or match.group("close") is not None
    if (match.group("open") is None) != (match.group("close") is None):
        raise ValueError("unbalanced money parentheses")
    if parenthesized and match.group("sign") is not None:
        raise ValueError("money value has two negative markers")
    amount = Decimal(match.group("amount").replace(",", ""))
    cents = int(amount * 100)
    if cents > _MAX_MONEY_CENTS:
        raise ValueError("money value exceeds the supported limit")
    negative = parenthesized or match.group("sign") is not None
    return -cents if negative else cents


class _SafeTextExtractor(HTMLParser):
    """Extract visible text without rendering HTML or resolving resources."""

    _BLOCKS: ClassVar[frozenset[str]] = frozenset(
        {"br", "div", "li", "p", "table", "td", "th", "tr", "h1", "h2", "h3"}
    )
    _SKIPPED: ClassVar[frozenset[str]] = frozenset({"head", "script", "style", "svg", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skipped_elements: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.casefold()
        if tag in self._SKIPPED:
            self._skipped_elements.append(tag)
        elif not self._skipped_elements and tag in self._BLOCKS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self._SKIPPED:
            if not self._skipped_elements or self._skipped_elements[-1] != tag:
                raise UnsupportedEmailError("E_HTML_BODY: malformed hidden element nesting")
            self._skipped_elements.pop()
        elif not self._skipped_elements and tag in self._BLOCKS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipped_elements:
            self._parts.append(data)

    def ensure_balanced(self) -> None:
        if self._skipped_elements:
            raise UnsupportedEmailError("E_HTML_BODY: unclosed hidden element")

    def lines(self) -> tuple[str, ...]:
        values: list[str] = []
        for raw_line in "".join(self._parts).splitlines():
            line = " ".join(unicodedata.normalize("NFKC", raw_line).split())
            if line:
                values.append(line)
        return tuple(values)


def _header(message: Message, name: str) -> str:
    values = message.get_all(name, []) or []
    if len(values) > 1:
        raise UnsupportedEmailError(f"E_HEADER_DUPLICATE: duplicate {name!r} header")
    return " ".join(str(values[0]).split()) if values else ""


def _header_datetime(message: Message, name: str) -> datetime:
    raw = _header(message, name)
    if not raw:
        raise UnsupportedEmailError(f"E_HEADER_DATE: missing {name!r} header")
    try:
        parsed = parsedate_to_datetime(raw)
    except TypeError, ValueError:
        raise UnsupportedEmailError(f"E_HEADER_DATE: invalid {name!r} header") from None
    if parsed.tzinfo is None:
        raise UnsupportedEmailError(f"E_HEADER_DATE: {name!r} has no timezone")
    return parsed


def _nested_messages(root: Message) -> tuple[Message, ...]:
    messages: list[Message] = [root]
    seen = {id(root)}
    for part in root.walk():
        if part.get_content_type() != "message/rfc822":
            continue
        payload = part.get_payload()
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, Message) and id(candidate) not in seen:
                messages.append(candidate)
                seen.add(id(candidate))
    return tuple(messages)


_SEVERE_MIME_DEFECTS: tuple[type[MessageDefect], ...] = (
    StartBoundaryNotFoundDefect,
    CloseBoundaryNotFoundDefect,
    NoBoundaryInMultipartDefect,
    MultipartInvariantViolationDefect,
    MissingHeaderBodySeparatorDefect,
    FirstHeaderLineIsContinuationDefect,
    MisplacedEnvelopeHeaderDefect,
    UndecodableBytesDefect,
)


def _reject_severe_defects(root: Message) -> None:
    for part in root.walk():
        for defect in part.defects:
            if isinstance(defect, _SEVERE_MIME_DEFECTS):
                raise UnsupportedEmailError("E_MIME: malformed MIME structure")


def _is_allowed_sender(message: Message, allowed_domains: frozenset[str]) -> bool:
    _, address = parseaddr(_header(message, "From"))
    _, separator, domain = address.casefold().rpartition("@")
    if not separator:
        return False
    normalized_domains = frozenset(value.strip(".").casefold() for value in allowed_domains)
    return any(
        domain == allowed or domain.endswith(f".{allowed}") for allowed in normalized_domains
    )


def _html_lines(message: Message) -> tuple[str, ...]:
    html_parts: list[Message] = []
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        if part.get_content_disposition() == "attachment":
            continue
        html_parts.append(part)
    if len(html_parts) != 1:
        raise UnsupportedEmailError("E_HTML_BODY: expected one non-attachment HTML body")

    part = html_parts[0]
    if isinstance(part, EmailMessage):
        content = part.get_content()
        html = str(content)
    else:
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            raise UnsupportedEmailError("E_HTML_BODY: unreadable HTML body")
        html = payload.decode(part.get_content_charset() or "utf-8", errors="strict")
    if len(html) > _MAX_BODY_CHARACTERS:
        raise UnsupportedEmailError("E_HTML_BODY: HTML body is too large")

    extractor = _SafeTextExtractor()
    extractor.feed(html)
    extractor.close()
    extractor.ensure_balanced()
    lines = extractor.lines()
    if not lines:
        raise UnsupportedEmailError("E_HTML_BODY: HTML body contains no readable text")
    return lines


def _subject_order_id(message: Message) -> str | None:
    match = _SUBJECT.fullmatch(_header(message, "Subject"))
    return match.group("order_id") if match else None


def _line_indexes(lines: tuple[str, ...], label: str) -> list[int]:
    folded = label.casefold()
    return [index for index, line in enumerate(lines) if line.casefold() == folded]


def _has_sentinels(lines: tuple[str, ...]) -> bool:
    labels = (
        "Order ID",
        "Delivery Slot",
        "Subtotal",
        "Delivery Fee",
        "Service Fee",
        "Total",
    )
    return all(len(_line_indexes(lines, label)) == 1 for label in labels)


def _select_source(
    root: Message, allowed_sender_domains: frozenset[str]
) -> tuple[Message, tuple[str, ...], str]:
    candidates: list[tuple[Message, tuple[str, ...], str]] = []
    for message in _nested_messages(root):
        order_id = _subject_order_id(message)
        if order_id is None or not _is_allowed_sender(message, allowed_sender_domains):
            continue
        lines = _html_lines(message)
        if _has_sentinels(lines):
            candidates.append((message, lines, order_id))
    if not candidates:
        raise UnsupportedEmailError("E_VENDOR_LAYOUT: no supported FairPrice order was found")
    if len(candidates) > 1:
        raise UnsupportedEmailError("E_VENDOR_LAYOUT: multiple FairPrice orders are ambiguous")
    return candidates[0]


def _unique_index(lines: tuple[str, ...], label: str) -> int:
    indexes = _line_indexes(lines, label)
    if not indexes:
        raise UnsupportedEmailError(f"E_FIELD_MISSING: missing {label!r}")
    if len(indexes) > 1:
        raise UnsupportedEmailError(f"E_FIELD_DUPLICATE: duplicate {label!r}")
    return indexes[0]


def _whole_money(line: str, *, field: str, allow_negative: bool = False) -> int:
    try:
        cents = parse_sgd_cents(line)
    except ValueError:
        raise UnsupportedEmailError(f"E_MONEY: invalid {field}") from None
    if not allow_negative and cents < 0:
        raise UnsupportedEmailError(f"E_MONEY: {field} cannot be negative")
    return cents


def _amount_after_label(lines: tuple[str, ...], label: str, *, required: bool = True) -> int:
    indexes = _line_indexes(lines, label)
    if not indexes:
        if required:
            raise UnsupportedEmailError(f"E_FIELD_MISSING: missing {label!r}")
        return 0
    if len(indexes) > 1:
        raise UnsupportedEmailError(f"E_FIELD_DUPLICATE: duplicate {label!r}")
    index = indexes[0]
    if index + 1 >= len(lines):
        raise UnsupportedEmailError(f"E_FIELD_MISSING: {label!r} has no value")
    return _whole_money(lines[index + 1], field=label)


def _parse_quantity(value: str) -> Decimal:
    if _QUANTITY.fullmatch(value) is None:
        raise UnsupportedEmailError("E_ITEM_QUANTITY: invalid item quantity")
    quantity = Decimal(value)
    if quantity <= 0:
        raise UnsupportedEmailError("E_ITEM_QUANTITY: item quantity must be positive")
    return quantity


def _inline_unit_price(value: str) -> int:
    matches = [match.group("value") for match in _INLINE_MONEY.finditer(value)]
    if len(matches) != 1:
        raise UnsupportedEmailError("E_ITEM_PRICE: expected one unit price")
    return _whole_money(matches[0], field="item unit price")


def _parse_item_group(lines: tuple[str, ...], index: int, line_number: int) -> ParsedItem:
    try:
        name, unit_description, quantity_text, line_total_text = lines[index : index + 4]
    except ValueError:
        raise UnsupportedEmailError("E_ITEM_LAYOUT: incomplete item row") from None
    if not name or len(name) > 500:
        raise UnsupportedEmailError("E_ITEM_NAME: invalid item name")
    if name.casefold() in {
        "subtotal",
        "delivery fee",
        "service fee",
        "container deposit",
        "redeem linkpoints",
        "total",
    }:
        raise UnsupportedEmailError("E_ITEM_NAME: summary label cannot be an item name")

    unit_price = _inline_unit_price(unit_description)
    quantity = _parse_quantity(quantity_text)
    net = _whole_money(line_total_text, field="item line total")
    gross_decimal = quantity * unit_price
    if gross_decimal != gross_decimal.to_integral_value():
        raise UnsupportedEmailError("E_ITEM_TOTAL: unit price times quantity is not an exact cent")
    gross = int(gross_decimal)
    if net > gross:
        raise UnsupportedEmailError("E_ITEM_TOTAL: line total exceeds unit price times quantity")
    try:
        return ParsedItem(
            line_number=line_number,
            name=name,
            external_sku=None,
            quantity=quantity,
            unit="item",
            unit_price_cents=unit_price,
            gross_cents=gross,
            discount_cents=gross - net,
            net_cents=net,
        )
    except ValidationError:
        raise UnsupportedEmailError("E_ITEM_INVALID: item failed validation") from None


def _parse_items(lines: tuple[str, ...]) -> tuple[ParsedItem, ...]:
    subtotal_index = _unique_index(lines, "Subtotal")
    count_indexes = [
        index for index, line in enumerate(lines[:subtotal_index]) if _ITEM_COUNT.fullmatch(line)
    ]
    if len(count_indexes) != 1:
        raise UnsupportedEmailError("E_ITEM_COUNT: expected one item-count marker")
    count_index = count_indexes[0]
    match = _ITEM_COUNT.fullmatch(lines[count_index])
    if match is None:
        raise UnsupportedEmailError("E_ITEM_COUNT: invalid item-count marker")
    expected_count = int(match.group("count"))

    items: list[ParsedItem] = []
    cursor = count_index + 1
    for line_number in range(1, expected_count + 1):
        if cursor + 4 > subtotal_index:
            raise UnsupportedEmailError("E_ITEM_LAYOUT: item count exceeds available rows")
        item = _parse_item_group(lines, cursor, line_number)
        items.append(item)
        cursor += 4
        while cursor < subtotal_index and "deposit" in lines[cursor].casefold():
            values = [match.group("value") for match in _INLINE_MONEY.finditer(lines[cursor])]
            if len(values) != 1 or _whole_money(values[0], field="item deposit note") < 0:
                raise UnsupportedEmailError("E_ITEM_DEPOSIT: invalid item deposit note")
            cursor += 1
    if cursor != subtotal_index:
        raise UnsupportedEmailError("E_ITEM_LAYOUT: unexpected text between items and subtotal")
    return tuple(items)


def _order_id_from_body(lines: tuple[str, ...]) -> str:
    index = _unique_index(lines, "Order ID")
    if index + 1 >= len(lines) or _ORDER_ID.fullmatch(lines[index + 1]) is None:
        raise UnsupportedEmailError("E_ORDER_ID: invalid body order ID")
    return lines[index + 1]


def _redeemed_linkpoints(lines: tuple[str, ...]) -> int:
    indexes = _line_indexes(lines, "Redeem LinkPoints")
    if not indexes:
        return 0
    if len(indexes) > 1:
        raise UnsupportedEmailError("E_FIELD_DUPLICATE: duplicate 'Redeem LinkPoints'")
    index = indexes[0]
    values: list[str] = []
    for line in lines[index + 1 : index + 3]:
        values.extend(match.group("value") for match in _INLINE_MONEY.finditer(line))
    if len(values) != 1:
        raise UnsupportedEmailError("E_LINKPOINTS: expected one redemption amount")
    amount = _whole_money(values[0], field="LinkPoints redemption", allow_negative=True)
    if amount > 0:
        raise UnsupportedEmailError("E_LINKPOINTS: redemption must be zero or negative")
    return abs(amount)


def _included_tax(lines: tuple[str, ...]) -> int:
    total_index = _unique_index(lines, "Total")
    indexes = [
        index
        for index, line in enumerate(lines[total_index + 1 :], start=total_index + 1)
        if re.search(r"\bGST\b", line, flags=re.IGNORECASE)
        and re.search(r"\bincl", line, flags=re.IGNORECASE)
    ]
    if len(indexes) != 1:
        raise UnsupportedEmailError("E_INCLUDED_TAX: expected one included-GST statement")
    index = indexes[0]
    if index + 1 >= len(lines):
        return 0
    try:
        amount = parse_sgd_cents(lines[index + 1])
    except ValueError:
        return 0
    if amount < 0:
        raise UnsupportedEmailError("E_INCLUDED_TAX: included GST cannot be negative")
    return amount


def _parse_delivery_at(lines: tuple[str, ...], *, source_sent_at: datetime) -> datetime:
    index = _unique_index(lines, "Delivery Slot")
    if index + 2 >= len(lines):
        raise UnsupportedEmailError("E_DELIVERY_TIME: delivery date or slot is missing")
    date_text = lines[index + 1]
    slot_text = lines[index + 2]

    delivery_date: date | None = None
    for date_format in ("%d %b %Y", "%d %B %Y"):
        try:
            delivery_date = datetime.strptime(date_text, date_format).date()
            break
        except ValueError:
            pass
    if delivery_date is None:
        source_date = source_sent_at.astimezone(_SINGAPORE).date()
        for year in (source_date.year, source_date.year + 1):
            try:
                candidate = datetime.strptime(f"{date_text} {year}", "%a, %d %b %Y").date()
            except ValueError:
                continue
            if candidate.strftime("%a").casefold() != date_text[:3].casefold():
                continue
            if source_date <= candidate <= source_date + timedelta(days=31):
                delivery_date = candidate
                break
    slot_match = _DELIVERY_SLOT.fullmatch(slot_text)
    if delivery_date is None or slot_match is None:
        raise UnsupportedEmailError("E_DELIVERY_TIME: unsupported delivery date or slot")

    def parse_slot_time(value: str) -> time:
        compact = value.replace(" ", "").upper()
        for time_format in ("%I%p", "%I:%M%p"):
            try:
                return datetime.strptime(compact, time_format).time()
            except ValueError:
                pass
        raise UnsupportedEmailError("E_DELIVERY_TIME: invalid delivery slot")

    start = parse_slot_time(slot_match.group("start"))
    end = parse_slot_time(slot_match.group("end"))
    if end <= start:
        raise UnsupportedEmailError("E_DELIVERY_TIME: delivery slot must end after it starts")
    return datetime.combine(delivery_date, start, tzinfo=_SINGAPORE)


def _parse_order(
    lines: tuple[str, ...], *, subject_order_id: str, source_sent_at: datetime
) -> ParsedOrder:
    body_order_id = _order_id_from_body(lines)
    if body_order_id.casefold() != subject_order_id.casefold():
        raise UnsupportedEmailError("E_ORDER_ID: subject and body order IDs disagree")

    items = _parse_items(lines)
    subtotal = _amount_after_label(lines, "Subtotal")
    if sum(item.net_cents for item in items) != subtotal:
        raise UnsupportedEmailError("E_SUBTOTAL: item line totals do not match subtotal")
    summary_total = _amount_after_label(lines, "Total")
    displayed_total_indexes = _line_indexes(lines, "Order Total")
    if len(displayed_total_indexes) > 1:
        raise UnsupportedEmailError("E_FIELD_DUPLICATE: duplicate 'Order Total'")
    if displayed_total_indexes:
        displayed_order_total = _amount_after_label(lines, "Order Total")
        if displayed_order_total != summary_total:
            raise UnsupportedEmailError("E_ORDER_TOTAL: displayed totals disagree")
    try:
        return ParsedOrder(
            retailer_slug="fairprice",
            retailer_name="FairPrice",
            retailer_country="SG",
            external_order_id=body_order_id,
            revision_kind="confirmation",
            # The acknowledgement body has no order-placement timestamp. The
            # email Date remains metadata.source_sent_at and is not relabelled.
            ordered_at=None,
            delivery_at=_parse_delivery_at(lines, source_sent_at=source_sent_at),
            currency="SGD",
            subtotal_cents=subtotal,
            discount_cents=_redeemed_linkpoints(lines),
            delivery_fee_cents=_amount_after_label(lines, "Delivery Fee"),
            service_fee_cents=_amount_after_label(lines, "Service Fee"),
            other_fee_cents=_amount_after_label(lines, "Container Deposit", required=False),
            # This template states GST as included in Total. It must not be
            # added again when reconciling the order-level arithmetic.
            tax_cents=0,
            included_tax_cents=_included_tax(lines),
            total_cents=summary_total,
            status="placed",
            items=items,
        )
    except ValidationError:
        raise UnsupportedEmailError("E_ORDER_TOTAL: order arithmetic failed validation") from None


def _parse_fairprice_email(
    raw: bytes,
    *,
    source_message_key: str | None,
    allowed_sender_domains: frozenset[str],
) -> ParsedEmail:
    if not raw:
        raise UnsupportedEmailError("E_MIME: email is empty")
    if len(raw) > _MAX_EMAIL_BYTES:
        raise UnsupportedEmailError("E_MIME: email is too large")
    if not allowed_sender_domains:
        raise UnsupportedEmailError("E_SENDER: no sender domains are allowed")
    try:
        root = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception:
        raise UnsupportedEmailError("E_MIME: malformed MIME message") from None
    _reject_severe_defects(root)

    source, lines, subject_order_id = _select_source(root, allowed_sender_domains)
    source_sent_at = _header_datetime(source, "Date")
    received_at = _header_datetime(root, "Date")
    source_subject = _header(source, "Subject")
    source_material = "\n".join(
        (_header(source, "Message-ID"), _header(source, "From"), source_subject, *lines)
    )
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    parsed_order = _parse_order(
        lines,
        subject_order_id=subject_order_id,
        source_sent_at=source_sent_at,
    )
    metadata = EmailMetadata(
        source_message_key=source_message_key or raw_sha256,
        rfc822_message_id=_header(root, "Message-ID") or None,
        original_message_id=_header(source, "Message-ID") or None,
        source_fingerprint=hashlib.sha256(source_material.encode("utf-8")).hexdigest(),
        sender=_header(source, "From"),
        recipient=_header(source, "To") or None,
        subject=_header(root, "Subject") or source_subject,
        received_at=received_at,
        source_sent_at=source_sent_at,
    )
    return ParsedEmail(metadata=metadata, order=parsed_order, parser_version=PARSER_VERSION)


def parse_fairprice_email(
    raw: bytes,
    *,
    source_message_key: str | None = None,
    allowed_sender_domains: frozenset[str] = PRODUCTION_FAIRPRICE_DOMAINS,
) -> ParsedEmail:
    """Parse one supported FairPrice order without rendering or network access."""

    try:
        return _parse_fairprice_email(
            raw,
            source_message_key=source_message_key,
            allowed_sender_domains=allowed_sender_domains,
        )
    except UnsupportedEmailError:
        raise
    except ValueError, LookupError, ArithmeticError, UnicodeError:
        raise UnsupportedEmailError("E_ORDER_DATA: invalid order data") from None
