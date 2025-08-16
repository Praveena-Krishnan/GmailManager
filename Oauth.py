from flask import Flask, redirect, request, session, render_template
import requests
import os
from dotenv import load_dotenv
import time
import sqlite3
import re
import database
import gmail_service
import gemini_service
from dateutil.parser import parse
from datetime import timedelta, timezone
import json

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

# --- Authentication Routes ---
@app.route("/")
def index():
    if "user" in session: return redirect("/recent_classified")
    return render_template("login.html")

@app.route("/login")
def login():
    scope = ("openid email profile https://mail.google.com/ https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/gmail.send")
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
    return redirect("/recent_classified")

# --- Application Routes ---
@app.route("/recent_classified")
def recent_classified_view():
    category_filter = request.args.get('category', None)
    classifications = database.get_recent_classifications(category_filter=category_filter)
    category_counts = database.get_category_counts()
    category_colors = {"Urgent": "danger", "To Respond": "warning", "Meeting": "primary", "FYI": "info", "Uncategorized": "secondary"}
    return render_template("history.html", classifications=classifications, counts=category_counts, category_colors=category_colors)

# In app.py

@app.route("/classification/<int:classification_id>")
def classification_detail_view(classification_id):
    classification = database.get_classification_by_id(classification_id)
    if not classification:
        return "Classification not found", 404

    # NEW: Fetch the corresponding event suggestion, if one exists
    suggestion = database.get_suggestion_by_classification_id(classification_id)

    # Logic to highlight important terms in the summary
    summary = classification['summary']
    if classification['important_terms']:
        terms = [term.strip() for term in classification['important_terms'].split(',')]
        for term in terms:
            if term:
                summary = re.sub(f'({re.escape(term)})', r'<span class="highlight">\1</span>', summary, flags=re.IGNORECASE)

    # MODIFIED: Pass the new 'suggestion' object to the template
    return render_template(
        "detail.html",
        classification=classification,
        highlighted_summary=summary,
        suggestion=suggestion
    )

@app.route("/send_reply/<int:classification_id>", methods=["POST"])
def send_reply(classification_id):
    tokens = session.get("tokens")
    if not tokens: return redirect("/")
    classification = database.get_classification_by_id(classification_id)
    if not classification: return "Error: Original message not found.", 404
    reply_body = request.form.get("reply_body")
    original_message = gmail_service.get_full_message(tokens.get("access_token"), classification['gmail_message_id'])
    if not original_message: return "Error: Could not fetch original thread info from Gmail.", 500
    thread_id = original_message.get('threadId')
    to_address = classification['sender']
    subject = f"Re: {classification['subject']}"
    success = gmail_service.send_reply(tokens.get("access_token"), to_address, subject, reply_body, thread_id)
    if success: return redirect("/recent_classified")
    else: return "Failed to send email.", 500

# --- Background Webhook Route ---
@app.route("/pubsub/push", methods=["POST"])
def pubsub_push():
    if PUBSUB_VERIFICATION_TOKEN and request.args.get("token") != PUBSUB_VERIFICATION_TOKEN: return "Unauthorized", 401
    envelope = request.get_json(force=True, silent=True)
    if not (envelope and "message" in envelope): return "Bad Request", 400
    try:
        global last_tokens
        access_token = last_tokens.get("access_token") or gmail_service.refresh_access_token(CLIENT_ID, CLIENT_SECRET, last_tokens.get("refresh_token"))
        if not access_token:
            print("Failed to get a valid access token.")
            return "No valid token", 200
        last_tokens['access_token'] = access_token

        message = gmail_service.get_latest_unread_message(access_token)
        if not message: return "OK", 200
        
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
        email_content = {"subject": subject, "sender": sender, "body": body}

        # AI Call 1: Classify Email
        classification_result = gemini_service.process_single_email_with_gemini(email_content)
        if not classification_result:
            print(f"Initial classification failed for message {mid}. Marking as read to avoid loops.")
            gmail_service.mark_as_read(access_token, mid)
            return "OK", 200

        # AI Call 2 (Conditional): Generate Smart Draft
        response_draft = classification_result.get('response_draft', "No draft.")
        if classification_result.get('category') == 'To Respond':
            thread_data = gmail_service.get_full_thread(access_token, thread_id)
            if thread_data and thread_data.get('messages'):
                conversation_str = "".join([f"--- Email From: {next((h['value'] for h in m['payload']['headers'] if h['name'].lower() == 'from'), '')} ---\n{gmail_service.get_email_body(m['payload'])}\n\n" for m in thread_data['messages']])
                new_draft = gemini_service.generate_draft_from_thread(conversation_str)
                if new_draft:
                    response_draft = new_draft
        classification_result['response_draft'] = response_draft

        # CORRECTED LOGIC: Save the main classification FIRST to get its ID
        try:
            classification_id = database.add_classification(mid, classification_result)
        except sqlite3.IntegrityError:
            print(f"Duplicate message (ID: {mid}) ignored.")
            gmail_service.mark_as_read(access_token, mid)
            return "OK", 200

        # AI Call 3 (Conditional): Find Events
        if classification_result.get('category') in ['Meeting', 'To Respond', 'Urgent']:
            event_result = gemini_service.find_event_in_email(email_content)
            if event_result and event_result.get('event_details'):
                print(f"Found a potential event: {event_result['event_details']['summary']}")
                database.add_suggestion(event_result['event_details'], classification_id)
        
        gmail_service.mark_as_read(access_token, mid)
        return "OK", 200
    except Exception as e:
        print(f"Push handler error: {e}")
        return "OK", 200
    
# In app.py

@app.route("/check_conflicts/<int:suggestion_id>")
def check_conflicts(suggestion_id):
    tokens = session.get("tokens")
    if not tokens: 
        return {"error": "Not authenticated"}, 401

    # Get the specific suggestion from the database
    suggestion = database.get_suggestion(suggestion_id)
    if not suggestion: 
        return {"error": "Suggestion not found"}, 404

    time_expression = suggestion['time_expression']
    
    try:
        # Parse the human-readable time from the database
        start_time = parse(time_expression)
        # Assume a 1-hour duration if no end time is specified
        end_time = start_time + timedelta(hours=1)
    except Exception as e:
        print(f"Date parsing error: {e}")
        return {"error": f"Could not understand the date/time: '{time_expression}'"}, 400

    # Format for Google Calendar API (RFC3339)
    start_iso = start_time.astimezone(timezone.utc).isoformat()
    end_iso = end_time.astimezone(timezone.utc).isoformat()

    # Check for conflicting events in Google Calendar
    calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    params = {
        'timeMin': start_iso,
        'timeMax': end_iso,
        'singleEvents': True,
        'orderBy': 'startTime'
    }
    res = requests.get(calendar_url, headers={"Authorization": f"Bearer {tokens.get('access_token')}"}, params=params)
    
    conflicts = []
    if res.status_code == 200:
        conflicts = [event.get('summary') for event in res.json().get('items', [])]
    else:
        print(f"Error checking calendar: {res.text}")

    # Placeholder for a short description (can be upgraded with another AI call later)
    short_description = "AI-suggested event"

    return {
        "details": {
            "summary": suggestion['summary'],
            "time_expression": time_expression
        },
        "short_description": short_description,
        "conflicts": conflicts
    }

# In app.py

# In app.py

# In app.py

@app.route("/schedule_event/<int:suggestion_id>")
def schedule_event(suggestion_id):
    tokens = session.get("tokens")
    if not tokens: return redirect("/")

    suggestion = database.get_suggestion(suggestion_id)
    if not suggestion: return "Error: Suggestion not found.", 404

    try:
        start_time = parse(suggestion['time_expression'])
        end_time = start_time + timedelta(hours=1)
    except Exception as e:
        return f"Error: Could not parse the time '{suggestion['time_expression']}'. Details: {e}", 500
    
    classification = database.get_classification_by_id(suggestion['source_email_id'])
    sender_email = classification['sender'] if classification else ''

    event = {
        'summary': suggestion['summary'],
        'description': f"Event created by Zentra based on email: {classification['subject']}",
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'attendees': [{'email': sender_email}]
    }
    
    # --- NEW: DETAILED LOGGING ---
    print("\n--- SCHEDULING EVENT ---")
    print(f"Original Time Expression: {suggestion['time_expression']}")
    print(f"Parsed Start Time (Local): {start_time}")
    print("Sending the following payload to Google Calendar:")
    print(json.dumps(event, indent=2))
    # --- END OF LOGGING ---

    calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    headers = {"Authorization": f"Bearer {tokens.get('access_token')}"}
    
    res = requests.post(calendar_url, headers=headers, json=event)

    # --- NEW: LOGGING THE RESPONSE ---
    print("\n--- GOOGLE CALENDAR RESPONSE ---")
    print(f"Status Code: {res.status_code}")
    print(f"Response Body: {res.text}")
    print("---------------------------\n")
    # --- END OF LOGGING ---

    if res.status_code in [200, 201]:
        database.update_suggestion_status(suggestion_id, 'accepted')
        return redirect("/recent_classified")
    else:
        # We will now see the detailed error from Google here
        return f"Error creating event. See terminal log for details.", 500
    
if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)