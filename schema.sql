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
    priority_analysis TEXT,
    category_reason TEXT,
    summary TEXT,
    important_terms TEXT,
    response_draft TEXT
);


-- ... (your suggested_events table can remain here if you created it) ...

CREATE TABLE suggested_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL ,
    type TEXT NOT NULL, -- 'meeting' or 'deadline'
    summary TEXT NOT NULL,
    time_expression TEXT NOT NULL, -- MODIFIED: Replaced start_time and end_time
    description TEXT,
    source_email_id INTEGER,
    FOREIGN KEY (source_email_id) REFERENCES classifications (id)
);

CREATE TABLE reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    summary TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active', -- active, completed
    source_email_id INTEGER,
    FOREIGN KEY (source_email_id) REFERENCES classifications (id)
);

CREATE TABLE user_settings (
    id INTEGER PRIMARY KEY,
    -- These are placeholders for now
    enable_auto_categorization BOOLEAN NOT NULL CHECK (enable_auto_categorization IN (0, 1)),
    enable_draft_suggestions BOOLEAN NOT NULL CHECK (enable_draft_suggestions IN (0, 1)),
    -- NEW: Columns for working hours
    work_start_time TEXT,
    work_end_time TEXT,
    work_timezone TEXT
);

-- Insert a single row with default settings
INSERT INTO user_settings (id, enable_auto_categorization, enable_draft_suggestions, work_start_time, work_end_time, work_timezone) 
VALUES (1, 1, 1, '09:00', '17:00', 'UTC');