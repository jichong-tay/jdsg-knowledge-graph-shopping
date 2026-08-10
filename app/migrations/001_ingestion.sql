CREATE TABLE IF NOT EXISTS schema_migrations (
    version       INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    checksum      TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    applied_at    TEXT,
    is_dirty      INTEGER NOT NULL DEFAULT 1 CHECK (is_dirty IN (0,1)),
    CHECK ((is_dirty = 1 AND applied_at IS NULL) OR
           (is_dirty = 0 AND applied_at IS NOT NULL))
) STRICT;

CREATE TABLE email_sync_state (
    account_key          TEXT PRIMARY KEY,
    gmail_history_id     TEXT,
    scan_watermark_at    TEXT NOT NULL,
    overlap_seconds      INTEGER NOT NULL DEFAULT 86400 CHECK (overlap_seconds >= 0),
    last_success_at      TEXT,
    last_error_at        TEXT,
    last_error           TEXT,
    updated_at           TEXT NOT NULL
) STRICT, WITHOUT ROWID;

CREATE TABLE email_messages (
    id                   INTEGER PRIMARY KEY,
    source_kind          TEXT NOT NULL CHECK (source_kind IN ('manual','gmail')),
    source_message_key   TEXT NOT NULL UNIQUE,
    gmail_message_id     TEXT,
    gmail_thread_id      TEXT,
    rfc822_message_id    TEXT,
    original_message_id  TEXT,
    source_fingerprint   TEXT NOT NULL,
    sender               TEXT NOT NULL,
    recipient            TEXT,
    subject              TEXT NOT NULL,
    received_at          TEXT NOT NULL,
    gmail_internal_at    TEXT,
    source_sent_at       TEXT,
    raw_sha256           TEXT NOT NULL UNIQUE,
    raw_path             TEXT NOT NULL UNIQUE,
    parse_status         TEXT NOT NULL DEFAULT 'pending'
                         CHECK (parse_status IN ('pending','parsed','ignored','failed','needs_review')),
    parser_version       TEXT,
    parse_error          TEXT,
    fetched_at           TEXT NOT NULL,
    parsed_at            TEXT
) STRICT;

CREATE UNIQUE INDEX idx_email_gmail_message_id
    ON email_messages(gmail_message_id) WHERE gmail_message_id IS NOT NULL;
CREATE INDEX idx_email_status_date
    ON email_messages(parse_status, received_at);
CREATE INDEX idx_email_original_message_id
    ON email_messages(original_message_id);
CREATE INDEX idx_email_source_fingerprint
    ON email_messages(source_fingerprint);

CREATE TABLE retailers (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    country     TEXT NOT NULL,
    created_at  TEXT NOT NULL
) STRICT;

CREATE TABLE brands (
    id               INTEGER PRIMARY KEY,
    canonical_name   TEXT NOT NULL,
    normalized_name  TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
) STRICT;

CREATE TABLE categories (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES categories(id),
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    CHECK (parent_id IS NULL OR parent_id <> id)
) STRICT;

CREATE TABLE products (
    id                INTEGER PRIMARY KEY,
    canonical_key     TEXT NOT NULL UNIQUE,
    canonical_name    TEXT NOT NULL,
    normalized_name   TEXT NOT NULL,
    brand_id          INTEGER REFERENCES brands(id),
    category_id       INTEGER REFERENCES categories(id),
    package_quantity  REAL CHECK (package_quantity IS NULL OR package_quantity > 0),
    package_unit      TEXT,
    variant           TEXT,
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
) STRICT;

CREATE INDEX idx_products_normalized_name ON products(normalized_name);
CREATE INDEX idx_products_category ON products(category_id);

CREATE TABLE retailer_products (
    id                 INTEGER PRIMARY KEY,
    retailer_id        INTEGER NOT NULL REFERENCES retailers(id),
    external_sku       TEXT,
    listing_key        TEXT NOT NULL,
    product_id         INTEGER NOT NULL REFERENCES products(id),
    latest_name        TEXT NOT NULL,
    latest_size_text   TEXT,
    match_status       TEXT NOT NULL DEFAULT 'provisional'
                       CHECK (match_status IN ('provisional','confirmed','rejected')),
    match_method       TEXT NOT NULL DEFAULT 'parser'
                       CHECK (match_method IN ('parser','rule','llm','manual')),
    match_confidence   REAL NOT NULL DEFAULT 1.0
                       CHECK (match_confidence >= 0.0 AND match_confidence <= 1.0),
    first_seen_at      TEXT NOT NULL,
    last_seen_at       TEXT NOT NULL,
    UNIQUE (retailer_id, listing_key)
) STRICT;

CREATE INDEX idx_retailer_products_product ON retailer_products(product_id);
CREATE UNIQUE INDEX idx_retailer_products_sku
    ON retailer_products(retailer_id, external_sku) WHERE external_sku IS NOT NULL;

CREATE TABLE product_aliases (
    id                INTEGER PRIMARY KEY,
    retailer_id       INTEGER REFERENCES retailers(id),
    normalized_alias  TEXT NOT NULL,
    display_alias     TEXT NOT NULL,
    product_id        INTEGER NOT NULL REFERENCES products(id),
    source_kind       TEXT NOT NULL CHECK (source_kind IN ('EXTRACTED','INFERRED','MANUAL')),
    confidence        REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    review_status     TEXT NOT NULL DEFAULT 'unreviewed'
                      CHECK (review_status IN ('unreviewed','accepted','rejected')),
    created_at        TEXT NOT NULL
) STRICT;

CREATE UNIQUE INDEX idx_product_aliases_retailer
    ON product_aliases(retailer_id, normalized_alias) WHERE retailer_id IS NOT NULL;
CREATE UNIQUE INDEX idx_product_aliases_global
    ON product_aliases(normalized_alias) WHERE retailer_id IS NULL;

CREATE TABLE orders (
    id                 INTEGER PRIMARY KEY,
    retailer_id        INTEGER NOT NULL REFERENCES retailers(id),
    external_order_id  TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    UNIQUE (retailer_id, external_order_id)
) STRICT;

CREATE TABLE order_revisions (
    id                   INTEGER PRIMARY KEY,
    order_id             INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    email_message_id     INTEGER NOT NULL REFERENCES email_messages(id),
    revision_number      INTEGER NOT NULL CHECK (revision_number > 0),
    revision_kind        TEXT NOT NULL
                         CHECK (revision_kind IN ('confirmation','amendment','receipt','refund','reparse')),
    revision_fingerprint TEXT NOT NULL,
    parser_version       TEXT NOT NULL,
    source_event_at      TEXT NOT NULL,
    ordered_at           TEXT,
    delivery_at          TEXT,
    currency             TEXT NOT NULL,
    subtotal_cents       INTEGER CHECK (subtotal_cents IS NULL OR subtotal_cents >= 0),
    discount_cents       INTEGER NOT NULL DEFAULT 0 CHECK (discount_cents >= 0),
    delivery_fee_cents   INTEGER NOT NULL DEFAULT 0 CHECK (delivery_fee_cents >= 0),
    service_fee_cents    INTEGER NOT NULL DEFAULT 0 CHECK (service_fee_cents >= 0),
    other_fee_cents      INTEGER NOT NULL DEFAULT 0 CHECK (other_fee_cents >= 0),
    tax_cents            INTEGER CHECK (tax_cents IS NULL OR tax_cents >= 0),
    included_tax_cents   INTEGER NOT NULL DEFAULT 0 CHECK (included_tax_cents >= 0),
    total_cents          INTEGER NOT NULL CHECK (total_cents >= 0),
    status               TEXT NOT NULL DEFAULT 'completed'
                         CHECK (status IN ('placed','completed','cancelled','refunded','unknown')),
    is_current           INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
    created_at           TEXT NOT NULL,
    UNIQUE (order_id, revision_number),
    UNIQUE (order_id, revision_fingerprint)
) STRICT;

CREATE UNIQUE INDEX idx_order_revisions_current
    ON order_revisions(order_id) WHERE is_current = 1;
CREATE INDEX idx_order_revisions_ordered_at ON order_revisions(ordered_at);

CREATE TABLE order_revision_sources (
    order_revision_id INTEGER NOT NULL REFERENCES order_revisions(id) ON DELETE CASCADE,
    email_message_id  INTEGER NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
    linked_at         TEXT NOT NULL,
    PRIMARY KEY (order_revision_id, email_message_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE order_items (
    id                    INTEGER PRIMARY KEY,
    order_revision_id     INTEGER NOT NULL REFERENCES order_revisions(id) ON DELETE CASCADE,
    line_number           INTEGER NOT NULL CHECK (line_number > 0),
    line_fingerprint      TEXT NOT NULL,
    retailer_product_id   INTEGER NOT NULL REFERENCES retailer_products(id),
    raw_name              TEXT NOT NULL,
    quantity              REAL NOT NULL CHECK (quantity > 0),
    unit                  TEXT NOT NULL DEFAULT 'item',
    unit_price_cents      INTEGER CHECK (unit_price_cents IS NULL OR unit_price_cents >= 0),
    gross_cents           INTEGER CHECK (gross_cents IS NULL OR gross_cents >= 0),
    discount_cents        INTEGER NOT NULL DEFAULT 0 CHECK (discount_cents >= 0),
    net_cents             INTEGER NOT NULL CHECK (net_cents >= 0),
    created_at            TEXT NOT NULL,
    UNIQUE (order_revision_id, line_number),
    UNIQUE (order_revision_id, line_fingerprint)
) STRICT;

CREATE INDEX idx_order_items_product ON order_items(retailer_product_id);

CREATE VIEW purchase_history AS
SELECT
    oi.id AS order_item_id,
    o.id AS order_id,
    rev.id AS order_revision_id,
    COALESCE(rev.delivery_at, rev.ordered_at, rev.source_event_at) AS purchase_event_at,
    rev.ordered_at,
    rev.delivery_at,
    o.external_order_id,
    r.slug AS retailer,
    p.id AS product_id,
    p.canonical_name,
    p.category_id,
    oi.quantity,
    oi.unit,
    oi.unit_price_cents,
    oi.net_cents
FROM order_items oi
JOIN order_revisions rev ON rev.id = oi.order_revision_id AND rev.is_current = 1
JOIN orders o ON o.id = rev.order_id
JOIN retailers r ON r.id = o.retailer_id
JOIN retailer_products rp ON rp.id = oi.retailer_product_id
JOIN products p ON p.id = rp.product_id
WHERE rev.status = 'completed';
