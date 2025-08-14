from flask import Flask, redirect, request, session, render_template_string
import requests
import os
from dotenv import load_dotenv
import json

load_dotenv()


app = Flask(__name__)
app.secret_key = "your_secret_key"

CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USER_INFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# --- Common HTML Structure with Bootstrap ---
BASE_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Google Integration</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  </head>
  <body>
    <div class="container my-5">
      <div class="card p-4 shadow-sm">
        <h1 class="card-title text-center mb-4">Google Integration App</h1>
        <div class="card-body">
          {content}
        </div>
        <div class="text-center mt-4">
          <a href="/" class="btn btn-secondary">Home</a>
        </div>
      </div>
    </div>
  </body>
</html>
"""

def render_with_bootstrap(content):
    """Renders the given content inside the Bootstrap base HTML."""
    return render_template_string(BASE_HTML.format(content=content))

@app.route("/")
def index():
    content = """
    <p class="text-center">Please log in to access your Gmail and Google Calendar.</p>
    <div class="text-center">
        <a href="/login" class="btn btn-primary btn-lg">Login with Google</a>
    </div>
    """
    return render_with_bootstrap(content)

@app.route("/login")
def login():
    scope = (
        "openid email profile "
        "https://mail.google.com/ "
        "https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/calendar "
        "https://www.googleapis.com/auth/calendar.events"
    )
    return redirect(f"{AUTH_URL}?client_id={CLIENT_ID}"
                    f"&redirect_uri={REDIRECT_URI}"
                    f"&response_type=code"
                    f"&scope={scope}"
                    f"&access_type=offline"
                    f"&prompt=consent")

@app.route("/callback")
def callback():
    code = request.args.get("code")
    token_data = {
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    token_res = requests.post(TOKEN_URL, data=token_data)
    tokens = token_res.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    user_info_res = requests.get(USER_INFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    user_info = user_info_res.json()

    session["user"] = user_info
    session["tokens"] = tokens

    content = f"""
    <div class="text-center">
        <h2 class="mb-3">Welcome, {user_info['name']}! 👋</h2>
        <p><strong>Email:</strong> {user_info['email']}</p>
        <p>You have successfully logged in. Please select an action below.</p>
    </div>
    <div class="list-group">
      <a href="/list_emails" class="list-group-item list-group-item-action">View Latest Email</a>
      <a href="/list_events" class="list-group-item list-group-item-action">View Calendar Events</a>
      <a href="/add_event" class="list-group-item list-group-item-action">Add a Calendar Event</a>
      <a href="/classify_emails" class="list-group-item list-group-item-action">Classify Emails (Gemini)</a>
    </div>
    """
    return render_with_bootstrap(content)

@app.route("/list_emails")
def list_emails():
    tokens = session.get("tokens")
    if not tokens:
        return redirect("/login")
    access_token = tokens.get("access_token")
    if not access_token:
        return redirect("/login")

    gmail_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    params = {"maxResults": 1, "labelIds": "INBOX"}
    res = requests.get(gmail_url, headers={"Authorization": f"Bearer {access_token}"}, params=params)
    if res.status_code != 200:
        content = f'<div class="alert alert-danger">Error fetching emails: {res.text}</div>'
        return render_with_bootstrap(content)
    
    messages = res.json().get("messages", [])
    if not messages:
        content = '<div class="alert alert-info">No emails found.</div>'
        return render_with_bootstrap(content)
    
    message_id = messages[0]["id"]
    message_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
    msg_res = requests.get(message_url, headers={"Authorization": f"Bearer {access_token}"}, params={"format": "full"})
    if msg_res.status_code != 200:
        content = f'<div class="alert alert-danger">Error fetching email details: {msg_res.text}</div>'
        return render_with_bootstrap(content)
        
    msg = msg_res.json()
    headers = msg.get("payload", {}).get("headers", [])
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(No Subject)")
    sender = next((h["value"] for h in headers if h["name"] == "From"), "(Unknown Sender)")
    snippet = msg.get("snippet", "")

    content = f"""
    <h2>Latest Email</h2>
    <div class="card">
        <div class="card-body">
            <h5 class="card-title"><strong>Subject:</strong> {subject}</h5>
            <h6 class="card-subtitle mb-2 text-muted"><strong>From:</strong> {sender}</h6>
            <p class="card-text"><strong>Snippet:</strong> {snippet}</p>
        </div>
    </div>
    """
    return render_with_bootstrap(content)

@app.route("/list_events")
def list_events():
    tokens = session.get("tokens")
    if not tokens:
        return redirect("/login")
    access_token = tokens.get("access_token")
    if not access_token:
        return redirect("/login")

    calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    res = requests.get(calendar_url, headers={"Authorization": f"Bearer {access_token}"})
    if res.status_code != 200:
        content = f'<div class="alert alert-danger">Error fetching events: {res.text}</div>'
        return render_with_bootstrap(content)
        
    events = res.json().get("items", [])
    if not events:
        content = '<div class="alert alert-info">No upcoming events found.</div>'
        return render_with_bootstrap(content)
        
    html = "<h2>Upcoming Calendar Events</h2><ul class='list-group'>"
    for event in events:
        summary = event.get("summary", "(No Title)")
        start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
        end = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", ""))
        html += f"""
        <li class="list-group-item">
            <h5 class="mb-1">{summary}</h5>
            <small class="text-muted"><strong>Start:</strong> {start}</small><br>
            <small class="text-muted"><strong>End:</strong> {end}</small>
        </li>
        """
    html += "</ul>"
    return render_with_bootstrap(html)


@app.route("/add_event", methods=["GET", "POST"])
@app.route("/add_event", methods=["GET", "POST"])
def add_event():
    tokens = session.get("tokens")
    if not tokens:
        return redirect("/login")
    access_token = tokens.get("access_token")
    if not access_token:
        return redirect("/login")

    if request.method == "POST":
        summary = request.form.get("summary")
        start = request.form.get("start")
        end = request.form.get("end")

        # Add a server-side check for empty fields
        if not summary or not start or not end:
            content = """
            <div class="alert alert-danger" role="alert">
                Error: Please fill in all the required fields (Title, Start, and End).
            </div>
            <a href="/add_event" class="btn btn-secondary">Try Again</a>
            """
            return render_with_bootstrap(content)

        # Add seconds if missing
        if len(start) == 16:
            start += ":00"
        if len(end) == 16:
            end += ":00"
            
        event = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": end, "timeZone": "Asia/Kolkata"},
        }
        
        calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        res = requests.post(
            calendar_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json=event
        )
        
        if res.status_code == 200 or res.status_code == 201:
            content = """
            <div class="alert alert-success" role="alert">Event added successfully!</div>
            <a href="/list_events" class="btn btn-primary">View Events</a>
            """
            return render_with_bootstrap(content)
        else:
            content = f'<div class="alert alert-danger" role="alert">Error adding event: {res.text}</div>'
            return render_with_bootstrap(content)
    
    # Simple HTML form for event creation (with datetime-local pickers)
    form_html = """
    <h2>Add Calendar Event</h2>
    <form method="post">
        <div class="mb-3">
            <label for="summary" class="form-label">Title</label>
            <input type="text" class="form-control" id="summary" name="summary" required>
        </div>
        <div class="mb-3">
            <label for="start" class="form-label">Start Time</label>
            <input type="datetime-local" class="form-control" id="start" name="start" required>
        </div>
        <div class="mb-3">
            <label for="end" class="form-label">End Time</label>
            <input type="datetime-local" class="form-control" id="end" name="end" required>
        </div>
        <button type="submit" class="btn btn-primary">Add Event</button>
    </form>
    """
    return render_with_bootstrap(form_html)

@app.route("/classify_emails")
def classify_emails():
    # Placeholder for Gemini classification logic
    # This function is not implemented in the original code, but we'll include a placeholder UI
    content = """
    <h2>Classify Emails</h2>
    <div class="alert alert-warning" role="alert">
        The email classification feature is not yet fully implemented.
    </div>
    <div class="list-group mt-3">
        <a href="#" class="list-group-item list-group-item-action">
            <div class="d-flex w-100 justify-content-between">
                <h5 class="mb-1">Example Email Subject</h5>
                <small class="text-muted">Category: Unclassified</small>
            </div>
            <p class="mb-1">This is a snippet of an example email to show how the UI would look.</p>
        </a>
        <a href="#" class="list-group-item list-group-item-action">
            <div class="d-flex w-100 justify-content-between">
                <h5 class="mb-1">Another Example Email</h5>
                <small class="text-muted">Category: Unclassified</small>
            </div>
            <p class="mb-1">This is another placeholder for a classified email.</p>
        </a>
    </div>
    """
    return render_with_bootstrap(content)


# The `fetch_latest_emails` function remains unchanged as it is a backend function.

if __name__ == "__main__":
    app.run(debug=False)