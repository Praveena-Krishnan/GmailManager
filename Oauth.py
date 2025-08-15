from flask import Flask, redirect, request, session, render_template_string
import requests
import os
from dotenv import load_dotenv
import json
import base64
import time # NEW: Import the time module
import database

load_dotenv()

if not os.path.exists(database.DATABASE_FILE):
    database.init_db()

# NEW: Record the time when the application starts.
# We'll only process emails that arrive AFTER this time.
# The value is in milliseconds to match Gmail's internalDate.
STARTUP_TIMESTAMP = int(time.time() * 1000)
print(f"Application started. Will only process emails received after timestamp: {STARTUP_TIMESTAMP}")

PUBSUB_TOPIC = os.getenv("PUBSUB_TOPIC")
PUBSUB_VERIFICATION_TOKEN = os.getenv("PUBSUB_VERIFICATION_TOKEN")
last_tokens = {}

# --- Gemini Email Processor (No Changes) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"

def process_single_email_with_gemini(email):
    prompt = f"""
    You are an email processing assistant. Your task is to analyze an email and return a structured JSON object.
    RULES:
    - Category must be one of: Urgent, To Respond, FYI, Meeting.
    - If a response is needed, the category must be "To Respond".
    - Confidence must be between 0.0 and 1.0.
    - The summary must be a concise, one-sentence overview.
    ACTUAL TASK: Analyze the following email and generate the JSON object.
    INPUT:
    Subject: {email['subject']}
    Sender: {email['sender']}
    Body: {email['body']}
    """
    data = {"contents": [{"parts": [{"text": prompt}]}],"generationConfig": {"responseMimeType": "application/json","responseSchema": {"type": "object","properties": {"subject": {"type": "string"}, "sender": {"type": "string"}, "body": {"type": "string"},"category": {"type": "string"}, "confidence": {"type": "number"}, "reason": {"type": "string"},"summary": {"type": "string"}, "important_terms": {"type": "array", "items": {"type": "string"}},"response_draft": {"type": "string"}},"required": ["subject", "sender", "category", "summary", "important_terms", "response_draft"]}}}
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=data)
        response.raise_for_status()
        candidates = response.json().get("candidates", [])
        if not candidates: return None
        return json.loads(candidates[0]["content"]["parts"][0]["text"])
    except Exception as e:
        print(f"Error in Gemini processing: {e}")
        return None

# --- Helper Functions (No Changes) ---
def get_email_body(payload):
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain': return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
            elif 'parts' in part:
                body = get_email_body(part)
                if body: return body
    elif 'body' in payload and 'data' in payload['body']: return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
    return ""

def start_gmail_watch(access_token):
    url = "https://gmail.googleapis.com/gmail/v1/users/me/watch"
    body = {"topicName": PUBSUB_TOPIC, "labelIds": ["INBOX"], "labelFilterAction": "include"}
    requests.post(url, headers={"Authorization": f"Bearer {access_token}","Content-Type": "application/json"}, json=body)

def refresh_access_token():
    global last_tokens
    if not last_tokens.get("refresh_token"): return None
    data = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "refresh_token": last_tokens["refresh_token"], "grant_type": "refresh_token"}
    r = requests.post(TOKEN_URL, data=data)
    if r.status_code == 200:
        new_tokens = r.json()
        last_tokens["access_token"] = new_tokens.get("access_token")
        return last_tokens["access_token"]
    return None

def mark_as_read(access_token, msg_id):
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}/modify"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {"removeLabelIds": ["UNREAD"]}
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code == 200:
        print(f"Successfully marked message {msg_id} as read.")
    else:
        print(f"Failed to mark message {msg_id} as read.")

# --- Flask App (No Changes)---
app = Flask(__name__)
app.secret_key = "your_secret_key"
CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI")
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
BASE_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Google Integration</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"></head><body><div class="container my-5"><div class="card p-4 shadow-sm"><h1 class="card-title text-center mb-4">Google Integration App</h1><div class="card-body">{content}</div><div class="text-center mt-4"><a href="/home" class="btn btn-secondary">Home</a></div></div></div></body></html>"""
def render_with_bootstrap(content): return render_template_string(BASE_HTML.format(content=content))

# --- Routes ---
@app.route("/")
def index():
    return render_with_bootstrap("""<p class="text-center">Please log in to your account.</p><div class="text-center"><a href="/login" class="btn btn-primary btn-lg">Login with Google</a></div>""")

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
    start_gmail_watch(tokens.get("access_token"))
    return redirect("/home")

@app.route("/home")
def home():
    user = session.get("user")
    if not user: return redirect("/")
    return render_with_bootstrap(f"""
    <div class="text-center"><h2 class="mb-3">Welcome, {user.get('name', 'User')}! 👋</h2></div>
    <div class="list-group">
      <a href="/recent_classified" class="list-group-item list-group-item-action">View Classification History</a>
    </div>""")

@app.route("/recent_classified")
def recent_classified_view():
    classifications = database.get_recent_classifications()
    if not classifications:
        return render_with_bootstrap('<div class="alert alert-info">No classified emails in history.</div>')
    items = "".join([f"""
        <li class="list-group-item">
            <div><strong>Subject:</strong> {r['subject']}</div>
            <div><strong>Sender:</strong> {r['sender']}</div>
            <div><strong>Category:</strong> {r['category']} (Confidence: {float(r['confidence'] or 0):.2f})</div>
            <div><strong>Summary:</strong> {r['summary']}</div>
        </li>""" for r in classifications])
    return render_with_bootstrap(f"<h2>Classification History</h2><ul class='list-group'>{items}</ul>")

# MODIFIED: pubsub_push now checks the email's timestamp
@app.route("/pubsub/push", methods=["POST"])
def pubsub_push():
    if PUBSUB_VERIFICATION_TOKEN and request.args.get("token") != PUBSUB_VERIFICATION_TOKEN: return "Unauthorized", 401
    envelope = request.get_json(force=True, silent=True)
    if not (envelope and "message" in envelope): return "Bad Request", 400
    try:
        global last_tokens
        access_token = last_tokens.get("access_token") or refresh_access_token()
        if not access_token: return "No access token", 200

        gmail_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        params = {"maxResults": 1, "labelIds": "INBOX", "q": "is:unread"}
        list_res = requests.get(gmail_url, headers={"Authorization": f"Bearer {access_token}"}, params=params)
        if list_res.status_code != 200: return "OK", 200
        
        messages = list_res.json().get("messages", [])
        if not messages: return "OK", 200
        
        mid = messages[0]["id"]
        msg_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}"
        get_res = requests.get(msg_url, headers={"Authorization": f"Bearer {access_token}"}, params={"format": "full"})
        if get_res.status_code != 200: return "OK", 200
        
        m = get_res.json()
        
        # NEW: Check if the email is older than when the app started
        email_timestamp = int(m.get('internalDate', 0))
        if email_timestamp < STARTUP_TIMESTAMP:
            print(f"Ignoring old email (ID: {mid}) from before app startup.")
            mark_as_read(access_token, mid) # Mark it as read to clear it from the queue
            return "OK", 200
            
        subject = next((h["value"] for h in m["payload"]["headers"] if h["name"].lower() == "subject"), "")
        sender = next((h["value"] for h in m["payload"]["headers"] if h["name"].lower() == "from"), "")
        body = get_email_body(m["payload"])
        result = process_single_email_with_gemini({"subject": subject, "sender": sender, "body": body})

        if result:
            database.add_classification(result)
            mark_as_read(access_token, mid)
        else:
            # If classification fails, still mark as read to prevent loops on a bad email.
            print(f"Classification failed for message {mid}. Marking as read to prevent loops.")
            mark_as_read(access_token, mid)
        
        return "OK", 200
    except Exception as e:
        print(f"Push handler error: {e}")
        return "OK", 200

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)
# --- Other Routes (No Changes Here) ---
@app.route("/list_events")
def list_events():
    # ... (code remains the same)
    tokens = session.get("tokens")
    if not tokens: return redirect("/login")
    access_token = tokens.get("access_token")
    if not access_token: return redirect("/login")
    calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    res = requests.get(calendar_url, headers={"Authorization": f"Bearer {access_token}"})
    if res.status_code != 200:
        return render_with_bootstrap(f'<div class="alert alert-danger">Error fetching events: {res.text}</div>')
    events = res.json().get("items", [])
    if not events:
        return render_with_bootstrap('<div class="alert alert-info">No upcoming events found.</div>')
    html = "<h2>Upcoming Calendar Events</h2><ul class='list-group'>"
    for event in events:
        summary = event.get("summary", "(No Title)")
        start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
        end = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", ""))
        html += f'<li class="list-group-item"><h5 class="mb-1">{summary}</h5><small class="text-muted"><strong>Start:</strong> {start}</small><br><small class="text-muted"><strong>End:</strong> {end}</small></li>'
    html += "</ul>"
    return render_with_bootstrap(html)

@app.route("/add_event", methods=["GET", "POST"])
def add_event():
    # ... (code remains the same)
    tokens = session.get("tokens")
    if not tokens: return redirect("/login")
    access_token = tokens.get("access_token")
    if not access_token: return redirect("/login")
    if request.method == "POST":
        summary = request.form.get("summary")
        start = request.form.get("start")
        end = request.form.get("end")
        if not summary or not start or not end:
            return render_with_bootstrap("""<div class="alert alert-danger" role="alert">Error: Please fill in all fields.</div><a href="/add_event" class="btn btn-secondary">Try Again</a>""")
        if len(start) == 16: start += ":00"
        if len(end) == 16: end += ":00"
        event = {"summary": summary, "start": {"dateTime": start, "timeZone": "Asia/Kolkata"}, "end": {"dateTime": end, "timeZone": "Asia/Kolkata"}}
        calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        res = requests.post(calendar_url, headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}, json=event)
        if res.status_code in [200, 201]:
            return render_with_bootstrap("""<div class="alert alert-success" role="alert">Event added successfully!</div><a href="/list_events" class="btn btn-primary">View Events</a>""")
        else:
            return render_with_bootstrap(f'<div class="alert alert-danger" role="alert">Error adding event: {res.text}</div>')
    form_html = """
    <h2>Add Calendar Event</h2>
    <form method="post">
        <div class="mb-3"><label for="summary" class="form-label">Title</label><input type="text" class="form-control" id="summary" name="summary" required></div>
        <div class="mb-3"><label for="start" class="form-label">Start Time</label><input type="datetime-local" class="form-control" id="start" name="start" required></div>
        <div class="mb-3"><label for="end" class="form-label">End Time</label><input type="datetime-local" class="form-control" id="end" name="end" required></div>
        <button type="submit" class="btn btn-primary">Add Event</button>
    </form>"""
    return render_with_bootstrap(form_html)

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)