# in database.py
import sqlite3

DATABASE_FILE = 'history.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    with open('schema.sql') as f:
        conn.executescript(f.read())
    conn.close()
    print("Database has been initialized.")



def add_classification(message_id, result):
    conn = get_db_connection()
    important_terms_str = ', '.join(result.get('important_terms', []))
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO classifications
           (gmail_message_id, subject, sender, body, category, confidence, priority_analysis, category_reason, summary, important_terms, response_draft)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (message_id, result.get('subject', 'No Subject'), result.get('sender', 'Unknown Sender'), result.get('body', ''),
         result.get('category', 'Uncategorized'), result.get('confidence', 0.0),
         result.get('priority_analysis', 'N/A'),
         result.get('category_reason', 'N/A'),
         result.get('summary', 'N/A'), important_terms_str, result.get('response_draft', 'N/A'))
    )
    last_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return last_id

# ... (get_recent_classifications and get_category_counts are unchanged) ...
def get_recent_classifications(category_filter=None, limit=25):
    conn = get_db_connection()
    query = 'SELECT * FROM classifications'
    params = []
    if category_filter:
        query += ' WHERE category = ?'
        params.append(category_filter)
    query += ' ORDER BY id DESC LIMIT ?'
    params.append(limit)
    classifications = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return classifications

def get_category_counts():
    conn = get_db_connection()
    counts = conn.execute('SELECT category, COUNT(id) as count FROM classifications GROUP BY category').fetchall()
    conn.close()
    return {row['category']: row['count'] for row in counts}

# DELETED: The check_if_exists function is no longer needed.



def get_classification_by_id(classification_id):
    """Retrieves a single classification by its database ID."""
    conn = get_db_connection()
    classification = conn.execute(
        'SELECT * FROM classifications WHERE id = ?', (classification_id,)
    ).fetchone()
    conn.close()
    return classification

# In database.py

def add_suggestion(event_details, source_email_id):
    conn = get_db_connection()
    conn.execute(
        # MODIFIED: Inserts the new time_expression field
        'INSERT INTO suggested_events (type, summary, time_expression, description, source_email_id) VALUES (?, ?, ?, ?, ?)',
        (event_details.get('type'), event_details.get('summary'),
         event_details.get('time_expression'), event_details.get('description'), source_email_id)
    )
    conn.commit()
    conn.close()
    
# Add this new function to database.py

def get_suggestion_by_classification_id(classification_id):
    """Finds a pending event suggestion linked to a classification ID."""
    conn = get_db_connection()
    suggestion = conn.execute(
        "SELECT * FROM suggested_events WHERE source_email_id = ? AND status = 'pending'",
        (classification_id,)
    ).fetchone()
    conn.close()
    return suggestion


# Add this new function to database.py

def get_suggestion(suggestion_id):
    """Retrieves a single event suggestion by its own ID."""
    conn = get_db_connection()
    suggestion = conn.execute(
        'SELECT * FROM suggested_events WHERE id = ?', (suggestion_id,)
    ).fetchone()
    conn.close()
    return suggestion