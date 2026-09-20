CREATE TABLE product_families (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    normalized_name TEXT NOT NULL UNIQUE CHECK (length(normalized_name) BETWEEN 1 AND 120),
    definition TEXT NOT NULL CHECK (length(definition) BETWEEN 1 AND 2000),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE product_family_memberships (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    family_id INTEGER NOT NULL REFERENCES product_families(id),
    created_at TEXT NOT NULL,
    UNIQUE(product_id, family_id)
) STRICT;
CREATE INDEX idx_family_memberships_family ON product_family_memberships(family_id, product_id);

CREATE TABLE product_family_events (
    id INTEGER PRIMARY KEY,
    membership_id INTEGER NOT NULL REFERENCES product_family_memberships(id),
    version INTEGER NOT NULL CHECK (version > 0),
    kind TEXT NOT NULL CHECK (kind IN ('proposed','accepted','rejected','withdrawn')),
    proposal_event_id INTEGER,
    origin TEXT CHECK (origin IS NULL OR origin IN ('manual','inferred')),
    method TEXT CHECK (method IS NULL OR length(method) BETWEEN 1 AND 120),
    rationale TEXT CHECK (rationale IS NULL OR length(rationale) BETWEEN 1 AND 2000),
    support_json TEXT CHECK (support_json IS NULL OR (json_valid(support_json) AND json_type(support_json)='array' AND json_array_length(support_json)<=20 AND length(CAST(support_json AS BLOB)) <= 8192)),
    review_reason TEXT CHECK (review_reason IS NULL OR length(review_reason) BETWEEN 1 AND 2000),
    created_at TEXT NOT NULL,
    UNIQUE(membership_id, version),
    UNIQUE(id, membership_id),
    FOREIGN KEY(proposal_event_id, membership_id) REFERENCES product_family_events(id, membership_id)
) STRICT;

CREATE TABLE family_commands (
    id TEXT PRIMARY KEY CHECK (length(id) = 32 AND id NOT GLOB '*[^0-9a-f]*'),
    operation TEXT NOT NULL CHECK (operation IN ('create_family','propose_membership','review_membership')),
    fingerprint TEXT NOT NULL CHECK (length(fingerprint) = 64),
    outcome_json TEXT NOT NULL CHECK (json_valid(outcome_json) AND json_type(outcome_json)='object'),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE graph_dataset_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    dataset_id TEXT NOT NULL UNIQUE CHECK (length(dataset_id) = 32),
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0)
) STRICT;
INSERT INTO graph_dataset_state (id, dataset_id) VALUES (1, lower(hex(randomblob(16))));

CREATE TRIGGER graph_dataset_state_guard BEFORE UPDATE OF dataset_id ON graph_dataset_state
BEGIN SELECT RAISE(ABORT, 'dataset_id is immutable'); END;
CREATE TRIGGER graph_dataset_state_delete BEFORE DELETE ON graph_dataset_state
BEGIN SELECT RAISE(ABORT, 'dataset state is immutable'); END;

CREATE TRIGGER family_membership_generation AFTER INSERT ON product_family_memberships
BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER family_generation AFTER INSERT ON product_families
BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER family_event_generation AFTER INSERT ON product_family_events
BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;

CREATE TRIGGER family_immutable_update BEFORE UPDATE ON product_families BEGIN SELECT RAISE(ABORT, 'family records are immutable'); END;
CREATE TRIGGER family_immutable_delete BEFORE DELETE ON product_families BEGIN SELECT RAISE(ABORT, 'family records are immutable'); END;
CREATE TRIGGER family_membership_immutable_update BEFORE UPDATE ON product_family_memberships BEGIN SELECT RAISE(ABORT, 'membership records are immutable'); END;
CREATE TRIGGER family_membership_immutable_delete BEFORE DELETE ON product_family_memberships BEGIN SELECT RAISE(ABORT, 'membership records are immutable'); END;
CREATE TRIGGER family_event_immutable_update BEFORE UPDATE ON product_family_events BEGIN SELECT RAISE(ABORT, 'event records are immutable'); END;
CREATE TRIGGER family_event_immutable_delete BEFORE DELETE ON product_family_events BEGIN SELECT RAISE(ABORT, 'event records are immutable'); END;
CREATE TRIGGER family_command_immutable_update BEFORE UPDATE ON family_commands BEGIN SELECT RAISE(ABORT, 'command records are immutable'); END;
CREATE TRIGGER family_command_immutable_delete BEFORE DELETE ON family_commands BEGIN SELECT RAISE(ABORT, 'command records are immutable'); END;
CREATE TRIGGER family_event_shape BEFORE INSERT ON product_family_events
WHEN (NEW.kind='proposed' AND (NEW.origin IS NULL OR NEW.method IS NULL OR NEW.rationale IS NULL OR NEW.proposal_event_id IS NOT NULL OR NEW.review_reason IS NOT NULL OR NEW.support_json IS NULL))
  OR (NEW.kind<>'proposed' AND (NEW.origin IS NOT NULL OR NEW.method IS NOT NULL OR NEW.rationale IS NOT NULL OR NEW.proposal_event_id IS NULL OR NEW.review_reason IS NULL OR NEW.support_json IS NOT NULL))
BEGIN SELECT RAISE(ABORT, 'invalid family event shape'); END;
CREATE TRIGGER family_event_proposal_guard BEFORE INSERT ON product_family_events
WHEN NEW.kind<>'proposed' AND NOT EXISTS (SELECT 1 FROM product_family_events WHERE id=NEW.proposal_event_id AND membership_id=NEW.membership_id AND kind='proposed')
BEGIN SELECT RAISE(ABORT, 'invalid proposal reference'); END;

CREATE TRIGGER graph_generation_retailers AFTER INSERT ON retailers BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_retailers_u AFTER UPDATE ON retailers BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_retailers_d AFTER DELETE ON retailers BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_products AFTER INSERT ON products BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_products_u AFTER UPDATE ON products BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_products_d AFTER DELETE ON products BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_listings AFTER INSERT ON retailer_products BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_listings_u AFTER UPDATE ON retailer_products BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_listings_d AFTER DELETE ON retailer_products BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_orders AFTER INSERT ON orders BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_orders_u AFTER UPDATE ON orders BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_orders_d AFTER DELETE ON orders BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_revisions AFTER INSERT ON order_revisions BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_revisions_u AFTER UPDATE ON order_revisions BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_revisions_d AFTER DELETE ON order_revisions BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_items AFTER INSERT ON order_items BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_items_u AFTER UPDATE ON order_items BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_items_d AFTER DELETE ON order_items BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_messages AFTER INSERT ON email_messages BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_messages_u AFTER UPDATE ON email_messages BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_messages_d AFTER DELETE ON email_messages BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_sources AFTER INSERT ON order_revision_sources BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_sources_u AFTER UPDATE ON order_revision_sources BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;
CREATE TRIGGER graph_generation_sources_d AFTER DELETE ON order_revision_sources BEGIN UPDATE graph_dataset_state SET generation=generation+1 WHERE id=1; END;

CREATE INDEX idx_order_revisions_graph_delivery
    ON order_revisions(is_current, delivery_at, id);
CREATE INDEX idx_order_revisions_graph_source
    ON order_revisions(email_message_id, id);
CREATE INDEX idx_revision_sources_graph_source
    ON order_revision_sources(email_message_id, order_revision_id);
