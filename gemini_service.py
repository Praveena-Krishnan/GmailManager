# in gemini_service.py

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

    ---
    RULES:
    - category: Must be one of: Urgent, To Respond, FYI, Meeting. If a response is needed, the category must be "To Respond".
    - confidence: A score from 0.0 to 1.0 based on your certainty.
        - Use a HIGH score (0.9-1.0) for explicit emails (e.g., "this is urgent", "please reply").
        - Use a MEDIUM score (0.7-0.89) for implicit requests or suggestions.
    - reason: A brief justification for the category choice, referencing specific phrases or intent from the email. For example, "The email asks a direct question" or "The subject contains 'urgent'."
    - summary: A concise, one-sentence, neutral overview of the email's content.
    ---

    ACTUAL TASK:
    Analyze the following email and generate the JSON object based on the rules above.

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
                # This 'required' list is the key to fixing the problem.
                "required": ["subject", "sender", "category", "confidence", "reason", "summary", "important_terms", "response_draft"]
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
    
def generate_draft_from_thread(conversation_thread):
    """
    NEW: A specialized function that analyzes a full thread to generate a smart response draft.
    """
    prompt = f"""
    You are an expert email assistant. You have been provided with an entire email conversation thread.
    Your task is to generate a concise, professional, and context-aware response draft to the LAST email in the thread.
    The draft should be ready to send.

    CONVERSATION THREAD:
    {conversation_thread}

    DRAFT YOUR RESPONSE:
    """
    # This prompt asks for a simple text response, not JSON.
    data = { "contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=data)
        response.raise_for_status()
        # Extract the plain text draft from the response
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"Error in Gemini draft generation: {e}")
        return None