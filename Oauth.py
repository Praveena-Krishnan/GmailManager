from flask import Flask, redirect, request, session, render_template
import requests
import os
from dotenv import load_dotenv
import time
import sqlite3
import re
import json
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse
import pytz
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

# --- Authentication Routes ---
@app.context_processor
def inject_counts():
    """Injects dynamic counts into all templates."""
    pending_reminders_count = database.get_pending_reminders_count()
    return dict(pending_reminders_count=pending_reminders_count)

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

@app.route("/classification/<int:classification_id>")
def classification_detail_view(classification_id):
    classification = database.get_classification_by_id(classification_id)
    if not classification: return "Classification not found", 404
    suggestion = database.get_suggestion_by_classification_id(classification_id)
    summary = classification['summary']
    if classification['important_terms']:
        terms = [term.strip() for term in classification['important_terms'].split(',')]
        for term in terms:
            if term:
                summary = re.sub(f'({re.escape(term)})', r'<span class="highlight">\1</span>', summary, flags=re.IGNORECASE)
    return render_template("detail.html", classification=classification, highlighted_summary=summary, suggestion=suggestion)

@app.route("/send_reply/<int:classification_id>", methods=["POST"])
def send_reply(classification_id):
    tokens = session.get("tokens")
    if not tokens: return redirect("/")
    classification = database.get_classification_by_id(classification_id)
    if not classification: return "Error: Original message not found.", 404
    reply_body = request.form.get("reply_body")
    
    # CORRECTED: Use get_full_message which exists in our service
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

        # Save the main classification FIRST to get its ID
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
                event_details = event_result['event_details']
                event_type = event_details.get('type')
                if event_type == 'meeting':
                    database.add_suggestion(event_details, classification_id)
                elif event_type == 'deadline':
                    database.add_reminder(
                        summary=event_details.get('summary'),
                        due_date=event_details.get('time_expression'),
                        source_email_id=classification_id
                    )
        
        gmail_service.mark_as_read(access_token, mid)
        return "OK", 200
    except Exception as e:
        print(f"Push handler error: {e}")
        return "OK", 200

@app.route("/check_conflicts/<int:suggestion_id>")
def check_conflicts(suggestion_id):
    tokens = session.get("tokens")
    if not tokens: return {"error": "Not authenticated"}, 401
    suggestion = database.get_suggestion(suggestion_id)
    if not suggestion: return {"error": "Suggestion not found"}, 404
    time_expression = suggestion['time_expression']
    try:
        start_time = parse(time_expression)
        end_time = start_time + timedelta(hours=1)
    except Exception as e:
        return {"error": f"Could not understand the date/time: '{time_expression}'"}, 400
    start_iso = start_time.astimezone(timezone.utc).isoformat()
    end_iso = end_time.astimezone(timezone.utc).isoformat()
    calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    params = {'timeMin': start_iso, 'timeMax': end_iso, 'singleEvents': True, 'orderBy': 'startTime'}
    res = requests.get(calendar_url, headers={"Authorization": f"Bearer {tokens.get('access_token')}"}, params=params)
    conflicts = [event.get('summary') for event in res.json().get('items', [])] if res.status_code == 200 else []
    return {"details": {"summary": suggestion['summary'], "time_expression": time_expression}, "conflicts": conflicts}

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
        'description': f"Event created by Zentra from email: {classification['subject']}",
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'attendees': [{'email': sender_email}]
    }
    calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    res = requests.post(calendar_url, headers={"Authorization": f"Bearer {tokens.get('access_token')}"}, json=event)
    if res.status_code in [200, 201]:
        database.update_suggestion_status(suggestion_id, 'accepted')
        return redirect("/recent_classified")
    else:
        return f"Error creating event: {res.text}", 500

@app.route("/calendar")
def calendar_view():
    tokens = session.get("tokens")
    if not tokens: return redirect("/")
    upcoming_events = gmail_service.get_upcoming_events(tokens.get('access_token'))
    calendar_events = [{"title": event['summary'], "start": event['start_time']} for event in upcoming_events]
    calendar_events_json = json.dumps(calendar_events)
    pending_suggestions = database.get_pending_suggestions()
    latest_suggestion = pending_suggestions[0] if pending_suggestions else None
    return render_template("calendar.html", upcoming_events_list=upcoming_events, latest_suggestion=latest_suggestion, calendar_events_json=calendar_events_json)

@app.route("/manual_schedule/<int:classification_id>", methods=["POST"])
def manual_schedule(classification_id):
    tokens = session.get("tokens")
    if not tokens: return redirect("/")
    summary = request.form.get("summary")
    start_time_str = request.form.get("start_time")
    try:
        start_time = datetime.fromisoformat(start_time_str)
        end_time = start_time + timedelta(hours=1)
    except (ValueError, TypeError):
        return "Invalid date format submitted.", 400
    classification = database.get_classification_by_id(classification_id)
    sender_email = classification['sender'] if classification else ''
    event = {
        'summary': summary, 'description': f"Event manually created by Zentra from email: {classification['subject']}",
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'attendees': [{'email': sender_email}]
    }
    calendar_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    res = requests.post(calendar_url, headers={"Authorization": f"Bearer {tokens.get('access_token')}"}, json=event)
    if res.status_code in [200, 201]:
        event_details = {"type": "meeting", "summary": summary, "time_expression": start_time.strftime("%B %d, %Y at %I:%M %p")}
        database.add_suggestion(event_details, classification_id, status='accepted')
        return redirect(f"/classification/{classification_id}")
    else:
        return f"Error creating event: {res.text}", 500

@app.route("/reminders")
def reminders_view():
    reminders_raw = database.get_reminders(status='active')
    reminders = []
    now = datetime.now()
    for r in reminders_raw:
        try:
            reminder = dict(r)
            due_date = parse(r['due_date'])
            reminder['due_date_formatted'] = due_date.strftime("%b %d, %Y at %I:%M %p")
            classification = database.get_classification_by_id(r['source_email_id'])
            reminder['email_subject'] = classification['subject'] if classification else "Unknown"
            reminder['is_overdue'] = due_date < now
            reminders.append(reminder)
        except Exception as e:
            print(f"Error processing reminder {r['id']}: {e}")
            continue
    return render_template("reminders.html", reminders=reminders)

@app.route("/complete_reminder/<int:reminder_id>")
def complete_reminder(reminder_id):
    database.update_reminder_status(reminder_id, 'completed')
    return redirect("/reminders")
    
# In app.py

@app.route("/calendar_command", methods=['POST'])
def calendar_command():
    tokens = session.get("tokens")
    if not tokens: return {"error": "Not authenticated"}, 401

    command_text = request.json.get('command')
    if not command_text: return {"error": "No command provided"}, 400

    ai_result = gemini_service.interpret_calendar_command(command_text)
    print("AI Interpretation:", ai_result)

    if "error" in ai_result:
        return {"error": ai_result['error']}, 400

    intent = ai_result.get('intent')
    access_token = tokens.get('access_token')

    if intent == 'create':
        try:
            time_desc = ai_result.get('time_description')
            if not time_desc:
                return {"error": "Please specify a time for the new event."}, 400

            start_time = parse(time_desc)
            end_time = start_time + timedelta(hours=1)
            event_details = {
                "summary": ai_result.get('event_description'),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat()
            }
            success = gmail_service.create_calendar_event(access_token, event_details)
            if success:
                return {"message": f"Success! Event '{event_details['summary']}' was scheduled."}
            else:
                return {"error": "Failed to create the event in Google Calendar."}, 500
        except Exception as e:
            return {"error": f"Could not understand the time: {e}"}, 400

    elif intent in ['delete', 'update']:
        find_query = ai_result.get('event_description')
        events = gmail_service.find_calendar_events(access_token, find_query)
        
        if not events: return {"error": f"I couldn't find any events matching '{find_query}'."}, 404
        if len(events) > 1: return {"error": f"I found multiple events. Please be more specific."}, 400
        
        event_to_modify = events[0]

        if intent == 'delete':
            success = gmail_service.delete_calendar_event(access_token, event_to_modify['id'])
            if success: return {"message": f"Success! The event '{event_to_modify['summary']}' was removed."}
            else: return {"error": "Found the event, but failed to remove it."}, 500
        
        elif intent == 'update':
            try:
                new_start = parse(ai_result.get('time_description'))
                original_start = parse(event_to_modify['start'].get('dateTime'))
                original_end = parse(event_to_modify['end'].get('dateTime'))
                duration = original_end - original_start
                new_end = new_start + duration
                
                updates = {
                    'start': {'dateTime': new_start.isoformat(), 'timeZone': 'Asia/Kolkata'},
                    'end': {'dateTime': new_end.isoformat(), 'timeZone': 'Asia/Kolkata'}
                }
                updated_event = gmail_service.modify_calendar_event(access_token, event_to_modify['id'], updates)
                if updated_event: return {"message": f"Success! Event moved to {new_start.strftime('%A at %I:%M %p')}."}
                else: return {"error": "Found the event, but failed to move it."}, 500
            except Exception as e:
                return {"error": f"Could not understand the new time: {e}"}, 400

    return {"error": "I don't know how to handle that command yet."}, 400

# Add this new route to app.py

# In app.py

@app.route("/settings")
def settings_view():
    # Fetch the user's current settings from the database
    settings = database.get_user_settings()
    
    # Fetch the total number of emails processed
    total_count = database.get_total_classifications_count()
    
    # Pass BOTH the settings object and the count to the template
    return render_template(
        "settings.html", 
        settings=settings, 
        emails_processed_count=total_count
    )
    
# In app.py

@app.route("/update_settings", methods=['POST'])
def update_settings():
    # Get the form data from the toggle switches and inputs
    settings = {
        'auto_categorization': 1 if 'auto_categorization' in request.form else 0,
        'draft_suggestions': 1 if 'draft_suggestions' in request.form else 0,
        'work_start_time': request.form.get('work_start_time'),
        'work_end_time': request.form.get('work_end_time'),
        'work_timezone': request.form.get('work_timezone')
    }
    # Save the new settings to the database
    database.update_user_settings(settings)
    # Redirect back to the settings page
    return redirect("/settings")
    
if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)