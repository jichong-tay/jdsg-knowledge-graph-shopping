-- Keys outlive deletion to fence stale draft submissions, without retaining content.
CREATE TABLE conversation_keys (
    id TEXT PRIMARY KEY,
    consumed INTEGER NOT NULL DEFAULT 0 CHECK (consumed IN (0, 1))
) STRICT;

CREATE TABLE conversations (
    id TEXT PRIMARY KEY REFERENCES conversation_keys(id),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 80),
    endpoint TEXT NOT NULL,
    model TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    deleting INTEGER NOT NULL DEFAULT 0 CHECK (deleting IN (0, 1)),
    created_at TEXT NOT NULL,
    activity_at TEXT NOT NULL
) STRICT;
CREATE INDEX idx_conversation_activity ON conversations(activity_at DESC, id DESC);

CREATE TABLE conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 4000),
    created_at TEXT NOT NULL
) STRICT;
CREATE INDEX idx_conversation_messages ON conversation_messages(conversation_id, id);
CREATE TRIGGER immutable_submitted_message BEFORE UPDATE ON conversation_messages
BEGIN SELECT RAISE(ABORT, 'Submitted messages are immutable'); END;

CREATE TABLE response_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'stopping', 'complete', 'failed', 'stopped', 'interrupted')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    text TEXT NOT NULL DEFAULT '' CHECK (length(CAST(text AS BLOB)) <= 65536),
    code TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
CREATE INDEX idx_attempt_message ON response_attempts(message_id, id);
-- There is one application-wide response slot, including cancellation cleanup.
CREATE UNIQUE INDEX idx_one_active_response ON response_attempts((1))
    WHERE status IN ('running', 'stopping');

CREATE TABLE conversation_tools (
    attempt_id INTEGER NOT NULL REFERENCES response_attempts(id) ON DELETE CASCADE,
    call_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position BETWEEN 1 AND 8),
    name TEXT NOT NULL,
    arguments_json TEXT NOT NULL CHECK (json_valid(arguments_json)
        AND length(CAST(arguments_json AS BLOB)) <= 4096),
    result_json TEXT CHECK (result_json IS NULL OR (json_valid(result_json)
        AND length(CAST(result_json AS BLOB)) <= 4096)),
    PRIMARY KEY (attempt_id, call_id),
    UNIQUE (attempt_id, position)
) STRICT;

-- Only identifiers survive deletion. No message, title or tool content is kept here.
CREATE TABLE conversation_commands (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversation_keys(id),
    fingerprint TEXT,
    outcome_json TEXT NOT NULL CHECK (json_valid(outcome_json))
) STRICT;
CREATE INDEX idx_conversation_commands ON conversation_commands(conversation_id);
