# In gemini_service.py

import os
import requests
import json
from dotenv import load_dotenv
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"

def process_single_email_with_gemini(email):
    """Sends email content to Gemini for classification and returns a structured dict."""
    prompt = f"""
    You are an email processing assistant. Your task is to analyze an email and return a structured JSON object.

    RULES:
    - Category must be one of: Urgent, To Respond, FYI, Meeting.
    - If a response is needed, the category must be "To Respond".
    - Confidence must be between 0.0 and 1.0.
    - The summary must be a concise, one-sentence overview.

    ACTUAL TASK:
    Analyze the following email and generate the JSON object.

    INPUT:
    Subject: {email['subject']}
    Sender: {email['sender']}
    Body: {email['body']}
    """
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"}, "sender": {"type": "string"}, "body": {"type": "string"},
                    "category": {"type": "string"}, "confidence": {"type": "number"}, "reason": {"type": "string"},
                    "summary": {"type": "string"}, "important_terms": {"type": "array", "items": {"type": "string"}},
                    "response_draft": {"type": "string"}
                },
                "required": ["subject", "sender", "category", "summary", "important_terms", "response_draft"]
            }
        }
    }
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=data)
        response.raise_for_status()
        candidates = response.json().get("candidates", [])
        if not candidates:
            print("Error: Gemini API returned no candidates.")
            return None
        return json.loads(candidates[0]["content"]["parts"][0]["text"])
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}\nResponse body: {response.text}")
        return None
    except Exception as e:
        print(f"Unexpected error in Gemini processing: {e}")
        return None