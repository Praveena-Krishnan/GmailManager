# In gmail_service.py

import requests
import base64

GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"

def get_latest_unread_message(access_token):
    """Fetches the latest unread message from the user's inbox."""
    url = f"{GMAIL_API_BASE_URL}/messages"
    params = {"maxResults": 1, "labelIds": "INBOX", "q": "is:unread"}
    headers = {"Authorization": f"Bearer {access_token}"}

    list_res = requests.get(url, headers=headers, params=params)
    if list_res.status_code != 200:
        print(f"Error listing messages: {list_res.text}")
        return None

    messages = list_res.json().get("messages", [])
    if not messages:
        return None

    msg_id = messages[0]['id']
    msg_url = f"{GMAIL_API_BASE_URL}/messages/{msg_id}"
    get_res = requests.get(msg_url, headers=headers, params={"format": "full"})
    if get_res.status_code != 200:
        print(f"Error getting message {msg_id}: {get_res.text}")
        return None

    return get_res.json()

def get_email_body(payload):
    """Extracts the plain text body from an email payload."""
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
    """Registers the push notification watch on the user's inbox."""
    url = f"{GMAIL_API_BASE_URL}/watch"
    body = {"topicName": topic_name, "labelIds": ["INBOX"]}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    requests.post(url, headers=headers, json=body)

def mark_as_read(access_token, msg_id):
    """Marks a specific message as read by removing the UNREAD label."""
    url = f"{GMAIL_API_BASE_URL}/messages/{msg_id}/modify"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {"removeLabelIds": ["UNREAD"]}
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code == 200:
        print(f"Successfully marked message {msg_id} as read.")
    else:
        print(f"Failed to mark message {msg_id} as read.")

def refresh_access_token(client_id, client_secret, refresh_token):
    """Refreshes the OAuth access token."""
    url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    r = requests.post(url, data=data)
    if r.status_code == 200:
        return r.json().get("access_token")
    return None