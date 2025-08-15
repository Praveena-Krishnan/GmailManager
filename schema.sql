-- in schema.sql
DROP TABLE IF EXISTS classifications;
DROP TABLE IF EXISTS suggested_events; -- Keeping this for our future feature

CREATE TABLE classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id TEXT UNIQUE NOT NULL, -- NEW: Added unique message ID
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    body TEXT,
    category TEXT,
    confidence REAL,
    reason TEXT,
    summary TEXT,
    important_terms TEXT,
    response_draft TEXT
);

-- ... (your suggested_events table can remain here if you created it) ...