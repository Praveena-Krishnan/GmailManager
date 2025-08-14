from flask import Flask, redirect, request, session, render_template_string
import requests
import os
from dotenv import load_dotenv
load_dotenv()


app = Flask(__name__)
app.secret_key = "your_secret_key"

CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USER_INFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

@app.route("/")
def index():
    return '<a href="/login">Login with Google (Gmail + Calendar Access)</a>'

@app.route("/login")
def login():
    scope = (
        "openid email profile "
        "https://mail.google.com/ "
        "https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/calendar"
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

    return f"""
    <h1>Welcome {user_info['name']}</h1>
    <p>Email: {user_info['email']}</p>
    <p>Access Token: {access_token}</p>
    <p>Refresh Token: {refresh_token}</p>
    <a href="/list_emails">List Gmail Emails</a><br>
    <a href="/list_events">List Calendar Events</a><br>
    <a href="/add_event">Add Calendar Event</a>
    """

@app.route("/list_emails")
def list_emails():
    tokens = session.get("tokens")
    if not tokens:
        return redirect("/login")
    access_token = tokens.get("access_token")
    if not access_token:
        return redirect("/login")

    # Get the latest message
    gmail_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    params = {"maxResults": 1, "labelIds": "INBOX"}
    res = requests.get(gmail_url, headers={"Authorization": f"Bearer {access_token}"}, params=params)
    if res.status_code != 200:
        return f"<h2>Error fetching emails: {res.text}</h2>"
    messages = res.json().get("messages", [])
    if not messages:
        return "<h2>No emails found.</h2>"

    # Get the details of the latest message
    message_id = messages[0]["id"]
    message_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
    msg_res = requests.get(message_url, headers={"Authorization": f"Bearer {access_token}"}, params={"format": "full"})
    if msg_res.status_code != 200:
        return f"<h2>Error fetching email details: {msg_res.text}</h2>"
    msg = msg_res.json()

    # Extract subject, sender, and snippet
    headers = msg.get("payload", {}).get("headers", [])
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(No Subject)")
    sender = next((h["value"] for h in headers if h["name"] == "From"), "(Unknown Sender)")
    snippet = msg.get("snippet", "")

    return f"""
    <h2>Latest Email</h2>
    <b>From:</b> {sender}<br>
    <b>Subject:</b> {subject}<br>
    <b>Snippet:</b> {snippet}<br>
    """

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
        return f"<h2>Error fetching events: {res.text}</h2>"
    events = res.json().get("items", [])
    if not events:
        return "<h2>No upcoming events found.</h2>"

    html = "<h2>Upcoming Calendar Events</h2><ul>"
    for event in events:
        summary = event.get("summary", "(No Title)")
        start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
        end = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", ""))
        html += f"<li><b>{summary}</b><br>Start: {start}<br>End: {end}</li><br>"
    html += "</ul>"
    return html

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
            return "<h2>Event added successfully!</h2><a href='/list_events'>View Events</a>"
        else:
            return f"<h2>Error adding event: {res.text}</h2>"

    # Simple HTML form for event creation (with datetime-local pickers)
    form_html = """
    <h2>Add Calendar Event</h2>
    <form method="post">
        Title: <input type="text" name="summary" required><br>
        Start: <input type="datetime-local" name="start" required><br>
        End: <input type="datetime-local" name="end" required><br>
        <input type="submit" value="Add Event">
    </form>
    """
    return render_template_string(form_html)

@app.route("/classify_emails")
def classify_emails():
    emails = fetch_latest_emails(4)
    if not emails:
        return "<h2>No emails found or not logged in.</h2>"
    result = classify_emails_with_gemini(emails)
    if not result:
        return "<h2>Could not classify emails.</h2>"
    html = "<h2>Classified Emails</h2><ul>"
    for email in result:
        html += f"<li><b>{email['subject']}</b> - <i>{email['category']}</i><br>{email['snippet']}</li><br>"
    html += "</ul>"
    return html

def fetch_latest_emails(n=4):
    """Fetch the latest n emails with subject and snippet."""
    tokens = session.get("tokens")
    if not tokens:
        return []
    access_token = tokens.get("access_token")
    if not access_token:
        return []

    gmail_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    params = {"maxResults": n, "labelIds": "INBOX"}
    res = requests.get(gmail_url, headers={"Authorization": f"Bearer {access_token}"}, params=params)
    if res.status_code != 200:
        return []
    messages = res.json().get("messages", [])
    emails = []
    for msg in messages:
        message_id = msg["id"]
        message_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
        msg_res = requests.get(message_url, headers={"Authorization": f"Bearer {access_token}"}, params={"format": "full"})
        if msg_res.status_code != 200:
            continue
        msg_data = msg_res.json()
        headers = msg_data.get("payload", {}).get("headers", [])
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(No Subject)")
        snippet = msg_data.get("snippet", "")
        emails.append({"subject": subject, "snippet": snippet})
    return emails

if __name__ == "__main__":
    app.run(debug=False)
