-- This line ensures we start with a fresh table each time the DB is initialized.
DROP TABLE IF EXISTS classifications;

-- This creates the table that will store all our email classification data.
CREATE TABLE classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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