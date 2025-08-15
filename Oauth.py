# In app.py

from flask import Flask, redirect, request, session, render_template_string
import requests
import os
from dotenv import load_dotenv
import time

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

# --- HTML Template ---
BASE_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Google Integration</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"></head><body><div class="container my-5"><div class="card p-4 shadow-sm"><h1 class="card-title text-center mb-4">Google Integration App</h1><div class="card-body">{content}</div><div class="text-center mt-4"><a href="/home" class="btn btn-secondary">Home</a></div></div></div></body></html>"""
def render_with_bootstrap(content): return render_template_string(BASE_HTML.format(content=content))

# --- Authentication Routes ---
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
    
    gmail_service.start_gmail_watch(tokens.get("access_token"), PUBSUB_TOPIC)
    return redirect("/home")

# --- Application Routes ---
@app.route("/home")
def home():
    user = session.get("user")
    if not user: return redirect("/")
    # MODIFIED: Added calendar links back
    return render_with_bootstrap(f"""
    <div class="text-center"><h2 class="mb-3">Welcome, {user.get('name', 'User')}! 👋</h2></div>
    <div class="list-group">
      <a href="/recent_classified" class="list-group-item list-group-item-action">View Classification History</a>
      <a href="/list_events" class="list-group-item list-group-item-action">View Calendar Events</a>
      <a href="/add_event" class="list-group-item list-group-item-action">Add a Calendar Event</a>
    </div>""")

@app.route("/recent_classified")
def recent_classified_view():
    classifications = database.get_recent_classifications()
    if not classifications:
        return render_with_bootstrap('<div class="alert alert-info">No classified emails in history.</div>')
    
    category_colors = {"Urgent": "danger", "To Respond": "warning", "Meeting": "primary", "FYI": "info", "Uncategorized": "secondary"}
    items = "".join([f"""
        <div class="card mb-3">
          <div class="card-header d-flex justify-content-between align-items-center">
            <strong>Subject: {r['subject']}</strong>
            <span class="badge bg-{category_colors.get(r['category'], 'secondary')}">{r['category']}</span>
          </div>
          <div class="card-body">
            <h6 class="card-subtitle mb-2 text-muted"><strong>From:</strong> {r['sender']}</h6>
            <p class="card-text"><strong>Summary:</strong> {r['summary']}</p>
          </div>
        </div>
        """ for r in classifications])
    return render_with_bootstrap(f"<h2>Classification History</h2>{items}")

# --- NEW: Calendar Routes Added Back ---
@app.route("/list_events")
def list_events():
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
        
        # Add seconds if missing from datetime-local input
        if len(start) == 16: start += ":00"
        if len(end) == 16: end += ":00"
            
        event = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": end, "timeZone": "Asia/Kolkata"},
        }
        
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


# --- Background Webhook Route ---
@app.route("/pubsub/push", methods=["POST"])
def pubsub_push():
    if PUBSUB_VERIFICATION_TOKEN and request.args.get("token") != PUBSUB_VERIFICATION_TOKEN: return "Unauthorized", 401
    
    envelope = request.get_json(force=True, silent=True)
    if not (envelope and "message" in envelope): return "Bad Request", 400
    
    try:
        global last_tokens
        access_token = last_tokens.get("access_token")
        if not access_token:
            new_access_token = gmail_service.refresh_access_token(CLIENT_ID, CLIENT_SECRET, last_tokens.get("refresh_token"))
            if not new_access_token: return "No valid token", 200
            access_token = new_access_token
            last_tokens['access_token'] = access_token

        message = gmail_service.get_latest_unread_message(access_token)
        if not message:
            return "OK", 200
        
        email_timestamp = int(message.get('internalDate', 0))
        if email_timestamp < STARTUP_TIMESTAMP:
            print(f"Ignoring old email (ID: {message['id']}) from before app startup.")
            gmail_service.mark_as_read(access_token, message['id'])
            return "OK", 200
            
        subject = next((h["value"] for h in message["payload"]["headers"] if h["name"].lower() == "subject"), "")
        sender = next((h["value"] for h in message["payload"]["headers"] if h["name"].lower() == "from"), "")
        body = gmail_service.get_email_body(message["payload"])

        result = gemini_service.process_single_email_with_gemini({"subject": subject, "sender": sender, "body": body})

        if result:
            database.add_classification(result)
            gmail_service.mark_as_read(access_token, message['id'])
        else:
            print(f"Classification failed for message {message['id']}. It will remain unread and be retried.")
        
        return "OK", 200
    except Exception as e:
        print(f"Push handler error: {e}")
        return "OK", 200

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)