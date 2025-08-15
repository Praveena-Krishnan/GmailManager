# In database.py

import sqlite3

DATABASE_FILE = 'history.db'

def get_db_connection():
    """Creates a database connection with a longer timeout."""
    # MODIFIED: Added a timeout of 10 seconds to prevent "database is locked" errors
    # during rapid notifications.
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database using the schema.sql file."""
    conn = get_db_connection()
    with open('schema.sql') as f:
        conn.executescript(f.read())
    conn.close()
    print("Database has been initialized.")

def add_classification(result):
    """Adds a new classification result to the database."""
    conn = get_db_connection()

    # MODIFIED: Use .get() with default values to prevent NOT NULL errors
    # if Gemini fails to return a specific field.
    subject = result.get('subject', 'No Subject Provided')
    sender = result.get('sender', 'Unknown Sender')
    body = result.get('body', '')
    category = result.get('category', 'Uncategorized')
    confidence = result.get('confidence', 0.0)
    reason = result.get('reason', 'No reason provided.')
    summary = result.get('summary', 'No summary provided.')
    important_terms_str = ', '.join(result.get('important_terms', []))
    response_draft = result.get('response_draft', 'No draft generated.')

    conn.execute(
        '''INSERT INTO classifications
           (subject, sender, body, category, confidence, reason, summary, important_terms, response_draft)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (subject, sender, body, category, confidence, reason, summary, important_terms_str, response_draft)
    )
    conn.commit()
    conn.close()
    
# Add this function to the end of database.py

def check_if_exists(subject, sender):
    """Checks if a classification with a similar subject and sender already exists."""
    conn = get_db_connection()
    # A simple check: if a record from the same sender with the same subject exists,
    # assume it's a duplicate notification. For more accuracy, you could also check the timestamp.
    record = conn.execute(
        'SELECT id FROM classifications WHERE subject = ? AND sender = ?', (subject, sender)
    ).fetchone()
    conn.close()
    return record is not None

def get_recent_classifications(limit=25):
    """Retrieves the most recent classification results from the database."""
    conn = get_db_connection()
    classifications = conn.execute(
        'SELECT * FROM classifications ORDER BY id DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return classifications

