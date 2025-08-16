# in gemini_service.py

import os
import requests
import json
from dotenv import load_dotenv
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"

# In gemini_service.py

def process_single_email_with_gemini(email):
    """Sends email content to Gemini for classification and returns a structured dict."""
    prompt = f"""
    You are an expert email analysis assistant. Your task is to analyze an email and return a structured JSON object.

    ---
    RULES:
    - priority_analysis: Explain WHY the email is a priority. Mention key factors like "deadline approaching", "request from manager", "external client inquiry", or "from your college". If not a priority, state "Standard priority".
    - category: Must be one of: Urgent, To Respond, FYI, Meeting.
    - category_reason: Explain the evidence for the category choice. E.g., "The email asks a direct question" or "Contains scheduling information".
    - confidence: A score from 0.0 to 1.0 based on your certainty of the categorization.
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
                    "category": {"type": "string"}, "confidence": {"type": "number"},
                    "priority_analysis": {"type": "string"},
                    "category_reason": {"type": "string"},
                    "summary": {"type": "string"}, "important_terms": {"type": "array", "items": {"type": "string"}},
                    "response_draft": {"type": "string"}
                    # The old 'reason' field is correctly removed from here.
                },
                # CORRECTED: The required list now matches all the fields we need.
                "required": [
                    "subject", "sender", "body", "category", "confidence",
                    "priority_analysis", "category_reason", "summary",
                    "important_terms", "response_draft"
                ]
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
    
    
    # Add this new function to the end of gemini_service.py
    
    # In gemini_service.py

def find_event_in_email(email):
    """A specialized function that ONLY looks for time-related text for an event."""
    prompt = f"""
    Your single task is to analyze an email to find a schedulable event and extract the exact text describing its time.
    - An event is a 'meeting' or a 'deadline'.
    - If an event is found, extract its details. The 'time_expression' should be the exact phrase from the email, like "next Tuesday at 3pm" or "on August 24th".
    - If no event is found, the 'event_details' field MUST be null.

    INPUT:
    Subject: {email['subject']}
    Body: {email['body']}
    """
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "event_details": {
                        "type": "object",
                        "nullable": True,
                        "properties": {
                            "type": {"type": "string", "enum": ["meeting", "deadline"]},
                            "summary": {"type": "string"},
                            "time_expression": {"type": "string"}, # MODIFIED
                            "description": {"type": "string"}
                        },
                        "required": ["type", "summary", "time_expression"]
                    }
                }, "required": ["event_details"]
            }
        }
    }
    # ... (The rest of the function for the API call is the same)
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=data)
        response.raise_for_status()
        candidates = response.json().get("candidates", [])
        if not candidates: return None
        return json.loads(candidates[0]["content"]["parts"][0]["text"])
    except Exception as e:
        print(f"Error in Gemini event finding: {e}")
        return None