import requests
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dateutil.parser import parse
from datetime import timedelta

GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"

def get_latest_unread_message(access_token):
    url = f"{GMAIL_API_BASE_URL}/messages"
    params = {"maxResults": 1, "labelIds": "INBOX", "q": "is:unread"}
    headers = {"Authorization": f"Bearer {access_token}"}
    list_res = requests.get(url, headers=headers, params=params)
    if list_res.status_code != 200:
        print(f"Error listing messages: {list_res.text}")
        return None
    messages = list_res.json().get("messages", [])
    if not messages: return None
    return get_full_message(access_token, messages[0]['id'])

# NEW FUNCTION to get a single message by its ID
def get_full_message(access_token, msg_id):
    """Fetches a single, complete message object by its ID."""
    url = f"{GMAIL_API_BASE_URL}/messages/{msg_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"format": "full"}
    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 200:
        return res.json()
    else:
        print(f"Error getting message {msg_id}: {res.text}")
        return None

def get_full_thread(access_token, thread_id):
    url = f"{GMAIL_API_BASE_URL}/threads/{thread_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"format": "full"}
    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 200:
        return res.json()
    else:
        print(f"Error getting thread {thread_id}: {res.text}")
        return None

def get_email_body(payload):
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
            elif 'parts' in part:
                body = get_email_body(part)
                if body: return body
    elif 'body' in payload and 'data' in payload['body']:
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
    return ""

def start_gmail_watch(access_token, topic_name):
    url = f"{GMAIL_API_BASE_URL}/watch"
    body = {"topicName": topic_name, "labelIds": ["INBOX"]}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json=body)

def mark_as_read(access_token, msg_id):
    url = f"{GMAIL_API_BASE_URL}/messages/{msg_id}/modify"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {"removeLabelIds": ["UNREAD"]}
    requests.post(url, headers=headers, json=payload)

def refresh_access_token(client_id, client_secret, refresh_token):
    url = "https://oauth2.googleapis.com/token"
    data = {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}
    r = requests.post(url, data=data)
    if r.status_code == 200:
        return r.json().get("access_token")
    return None

def send_reply(access_token, to_address, subject, body, thread_id):
    url = f"{GMAIL_API_BASE_URL}/messages/send"
    headers = {"Authorization": f"Bearer {access_token}"}
    message = MIMEText(body)
    message['to'] = to_address
    message['subject'] = subject
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    payload = {'raw': raw_message, 'threadId': thread_id}
    r = requests.post(url, headers=headers, json=payload)
    return r.status_code == 200

# Add this new function to gmail_service.py
from datetime import datetime, timezone

def get_upcoming_events(access_token, max_results=10):
    """Fetches upcoming events from the user's primary calendar."""
    url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events"
    
    # Get events from now onwards, ordered by start time
    now = datetime.now(timezone.utc).isoformat()
    params = {
        'maxResults': max_results,
        'singleEvents': True,
        'orderBy': 'startTime',
        'timeMin': now
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    
    res = requests.get(url, headers=headers, params=params)
    if res.status_code != 200:
        print(f"Error fetching calendar events: {res.text}")
        return []

    events = []
    for item in res.json().get('items', []):
        start = item.get('start', {}).get('dateTime', item.get('start', {}).get('date'))
        events.append({
            'summary': item.get('summary', 'No Title'),
            'start_time': start,
            'attendees': len(item.get('attendees', []))
        })
    return events


def create_calendar_event(access_token, event_details):
    """Creates a new event on the user's primary calendar."""
    try:
        start_time = parse(event_details['start_time'])
        end_time = parse(event_details['end_time'])
    except Exception as e:
        print(f"Could not parse event times: {e}")
        return False
        
    event = {
        'summary': event_details.get('summary'),
        'description': event_details.get('description'),
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
    }
    
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    headers = {"Authorization": f"Bearer {access_token}"}
    res = requests.post(url, headers=headers, json=event)

    if res.status_code in [200, 201]:
        print(f"Successfully created event: {event.get('summary')}")
        return True
    else:
        print(f"Error creating event: {res.text}")
        return False
    
# Add these two functions to gmail_service.py

def find_calendar_events(access_token, query_text):
    """Searches for calendar events based on a text query."""
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    params = {'q': query_text, 'maxResults': 5}
    headers = {"Authorization": f"Bearer {access_token}"}
    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 200:
        return res.json().get('items', [])
    else:
        print(f"Error finding events: {res.text}")
        return []

def delete_calendar_event(access_token, event_id):
    """Deletes a specific calendar event by its ID."""
    url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    res = requests.delete(url, headers=headers)
    return res.status_code == 204 # 204 No Content is the success status for delete

# Add this new function to gmail_service.py

def modify_calendar_event(access_token, event_id, updates):
    """Modifies an existing calendar event with the provided updates."""
    url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    
    res = requests.patch(url, headers=headers, json=updates)
    
    if res.status_code == 200:
        print(f"Successfully modified event {event_id}")
        return res.json()
    else:
        print(f"Error modifying event: {res.text}")
        return None