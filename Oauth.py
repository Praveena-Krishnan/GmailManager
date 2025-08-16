# In app.py

from flask import Flask, redirect, request, session, render_template # MODIFIED
import requests
import os
from dotenv import load_dotenv
import time
import sqlite3
import re
import database
import gmail_service
import gemini_service

load_dotenv()

if not os.path.exists(database.DATABASE_FILE):
    database.init_db()

STARTUP_TIMESTAMP = int(time.time() * 1000)
print(f"Application started. Ignoring emails received before timestamp: {STARTUP_TIMESTAMP}")

# --- App Configuration ---
app = Flask(__name__)
app.secret_key = "your_secret_key"
CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI")
PUBSUB_TOPIC = os.getenv("PUBSUB_TOPIC")
PUBSUB_VERIFICATION_TOKEN = os.getenv("PUBSUB_VERIFICATION_TOKEN")
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

last_tokens = {}

# DELETED: The old BASE_HTML string and render_with_bootstrap function are gone.

# --- Authentication Routes ---
@app.route("/")
def index():
    # If user is already logged in, redirect to the main inbox page
    if "user" in session:
        return redirect("/recent_classified")
    
    # MODIFIED: Render the new, professional login page
    return render_template("login.html")

@app.route("/login")
def login():
    scope = ("openid email profile https://mail.google.com/ https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/calendar.events")
    return redirect(f"{AUTH_URL}?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope={scope}&access_type=offline&prompt=consent")

@app.route("/callback")
def callback():
    code = request.args.get("code")
    token_data = {"code": code, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code"}
    tokens = requests.post(TOKEN_URL, data=token_data).json()
    user_info = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {tokens.get('access_token')}"}).json()
    
    session["user"] = user_info
    session["tokens"] = tokens
    
    global last_tokens
    last_tokens = tokens.copy()
    
    gmail_service.start_gmail_watch(tokens.get("access_token"), PUBSUB_TOPIC)
    # MODIFIED: Redirect to the main inbox page after login
    return redirect("/recent_classified")

# --- Application Routes ---
# DELETED: The old /home route is no longer needed, /recent_classified is the new home.


@app.route("/recent_classified")
def recent_classified_view():
    category_filter = request.args.get('category', None)
    
    # Fetch all the necessary data from the database
    classifications = database.get_recent_classifications(category_filter=category_filter)
    category_counts = database.get_category_counts()
    
    category_colors = {
        "Urgent": "danger", "To Respond": "warning", "Meeting": "primary",
        "FYI": "info", "Uncategorized": "secondary"
    }

    # Pass the raw data directly to the template
    return render_template(
        "history.html",
        classifications=classifications,
        counts=category_counts,
        category_colors=category_colors
    )
    
    

@app.route("/pubsub/push", methods=["POST"])
def pubsub_push():
    if PUBSUB_VERIFICATION_TOKEN and request.args.get("token") != PUBSUB_VERIFICATION_TOKEN: return "Unauthorized", 401
    
    envelope = request.get_json(force=True, silent=True)
    if not (envelope and "message" in envelope): return "Bad Request", 400
    
    try:
        global last_tokens
        access_token = last_tokens.get("access_token") or gmail_service.refresh_access_token(
            CLIENT_ID, CLIENT_SECRET, last_tokens.get("refresh_token")
        )
        if not access_token:
            print("Failed to get a valid access token.")
            return "No valid token", 200
        last_tokens['access_token'] = access_token

        message = gmail_service.get_latest_unread_message(access_token)
        if not message:
            return "OK", 200
        
        mid = message.get('id')
        thread_id = message.get('threadId')
        
        email_timestamp = int(message.get('internalDate', 0))
        if email_timestamp < STARTUP_TIMESTAMP:
            print(f"Ignoring old email (ID: {mid}) from before app startup.")
            gmail_service.mark_as_read(access_token, mid)
            return "OK", 200
            
        subject = next((h["value"] for h in message["payload"]["headers"] if h["name"].lower() == "subject"), "")
        sender = next((h["value"] for h in message["payload"]["headers"] if h["name"].lower() == "from"), "")
        body = gmail_service.get_email_body(message["payload"])

        # STEP 1: Perform a quick classification on the latest email ONLY.
        result = gemini_service.process_single_email_with_gemini({"subject": subject, "sender": sender, "body": body})

        if not result:
             print(f"Initial classification failed for message {mid}. Marking as read to avoid loops on bad emails.")
             gmail_service.mark_as_read(access_token, mid)
             return "OK", 200

        # STEP 2: If the category is "To Respond", get the full thread and generate a better draft.
        if result.get('category') == 'To Respond':
            print(f"Category is 'To Respond'. Fetching full thread {thread_id} for a better draft...")
            thread_data = gmail_service.get_full_thread(access_token, thread_id)
            if thread_data and thread_data.get('messages'):
                conversation_str = ""
                for i, msg_in_thread in enumerate(thread_data['messages']):
                    headers = msg_in_thread['payload']['headers']
                    msg_sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                    msg_body = gmail_service.get_email_body(msg_in_thread['payload'])
                    conversation_str += f"--- Email {i+1} From: {msg_sender} ---\n{msg_body}\n\n"
                
                new_draft = gemini_service.generate_draft_from_thread(conversation_str)
                if new_draft:
                    print("Successfully generated a new draft based on the full thread.")
                    result['response_draft'] = new_draft
        
        # Now, save the final result using the robust de-duplication method
        try:
            database.add_classification(mid, result)
            gmail_service.mark_as_read(access_token, mid)
        except sqlite3.IntegrityError:
            # This error happens if the UNIQUE constraint fails, meaning it's a duplicate.
            print(f"Duplicate message (ID: {mid}) ignored by database UNIQUE constraint.")
            gmail_service.mark_as_read(access_token, mid)
        
        return "OK", 200
    except Exception as e:
        print(f"Push handler error: {e}")
        return "OK", 200
    



# Replace the existing detail view function in app.py
@app.route("/classification/<int:classification_id>")
def classification_detail_view(classification_id):
    classification = database.get_classification_by_id(classification_id)
    if not classification:
        return "Classification not found", 404

    # Logic to highlight important terms in the summary
    summary = classification['summary']
    if classification['important_terms']:
        # Get a list of terms, stripping any extra whitespace
        terms = [term.strip() for term in classification['important_terms'].split(',')]
        for term in terms:
            if term: # Ensure term is not an empty string
                # Use regex for a case-insensitive replacement
                summary = re.sub(f'({re.escape(term)})', r'<span class="highlight">\1</span>', summary, flags=re.IGNORECASE)

    return render_template("detail.html", classification=classification, highlighted_summary=summary)


@app.route("/send_reply/<int:classification_id>", methods=["POST"])
def send_reply(classification_id):
    tokens = session.get("tokens")
    if not tokens: return redirect("/")
    
    classification = database.get_classification_by_id(classification_id)
    if not classification:
        return "Error: Original message not found.", 404

    reply_body = request.form.get("reply_body")
    
    # We need the original thread ID to send a proper reply
    # This requires fetching the original message from Gmail again
    original_message = gmail_service.get_full_message(tokens.get("access_token"), classification['gmail_message_id'])
    if not original_message:
        return "Error: Could not fetch original thread info from Gmail.", 500

    thread_id = original_message.get('threadId')
    
    # The 'To' address is the original sender
    to_address = classification['sender']
    # The subject of a reply is typically "Re: [Original Subject]"
    subject = f"Re: {classification['subject']}"

    success = gmail_service.send_reply(tokens.get("access_token"), to_address, subject, reply_body, thread_id)

    if success:
        # After sending, redirect back to the inbox
        return redirect("/recent_classified")
    else:
        return "Failed to send email.", 500
    
if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)