import os
import requests
import json
from dotenv import load_dotenv
import time
from datetime import datetime

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"


# --- Central API caller with retry logic ---
def _call_gemini_api_with_retry(data, max_retries=3):
    """A robust, internal function to call the Gemini API with retry logic."""
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    
    for attempt in range(max_retries):
        try:
            response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=data)
            response.raise_for_status()
            
            candidates = response.json().get("candidates", [])
            if not candidates:
                print("Error: Gemini API returned no candidates.")
                return None

            if "responseSchema" in data.get("generationConfig", {}):
                return json.loads(candidates[0]["content"]["parts"][0]["text"])
            else:
                return candidates[0]["content"]["parts"][0]["text"]

        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code in [429, 503]:
                delay = (2 ** attempt) + 1
                print(f"API busy ({http_err.response.status_code}). Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print(f"HTTP error occurred: {http_err}\nResponse body: {http_err.response.text}")
                return None
        except Exception as e:
            print(f"An unexpected error occurred during API call: {e}")
            return None
    
    print("API call failed after multiple retries.")
    return None


def process_single_email_with_gemini(email):
    """Performs the main classification and analysis of an email."""
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
                    "summary": {"type": "string"},
                    "important_terms": {
                        "type": "array",
                        # CORRECTED: Was {"string"}, now {"type": "string"}
                        "items": {"type": "string"}
                    },
                    "response_draft": {"type": "string"}
                },
                "required": ["subject", "sender", "body", "category", "confidence", "priority_analysis", "category_reason", "summary", "important_terms", "response_draft"]
            }
        }
    }
    return _call_gemini_api_with_retry(data)


def generate_draft_from_thread(conversation_thread):
    """Analyzes a full thread to generate a smart response draft."""
    prompt = f"""
    You are an expert email assistant. You have been provided with an entire email conversation thread.
    Your task is to generate a concise, professional, and context-aware response draft to the LAST email in the thread.
    The draft should be ready to send.

    CONVERSATION THREAD:
    {conversation_thread}

    DRAFT YOUR RESPONSE:
    """
    data = { "contents": [{"parts": [{"text": prompt}]}]}
    return _call_gemini_api_with_retry(data)


def find_event_in_email(email):
    """A specialized function that ONLY looks for schedulable events in an email."""
    prompt = f"""
    Your single task is to analyze an email to find a schedulable event and extract the exact text describing its time.

    ---
    RULES:
    - An event is a 'meeting' or a 'deadline'.
    - If an event is found, extract its details. The 'time_expression' should be the exact phrase from the email, like "next Tuesday at 3pm" or "on August 24th".
    - If the email mentions a date but no specific time, assume a standard business time of 10:00 AM.
    - If no event is found, the 'event_details' field MUST be null.
    ---
    EXAMPLE:
    INPUT:
    Subject: Project Sync
    Body: Hi team, let's sync up tomorrow, August 17th, at 2:30 PM to discuss the new designs.
    OUTPUT JSON:
    {{
        "event_details": {{
            "type": "meeting",
            "summary": "Project Sync",
            "time_expression": "August 17th, 2025 at 2:30 PM",
            "description": "Discuss the new designs."
        }}
    }}
    ---

    ACTUAL TASK:
    Analyze the following email and generate the JSON output.

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
                        "type": "object", "nullable": True,
                        "properties": {
                            "type": {"type": "string", "enum": ["meeting", "deadline"]},
                            "summary": {"type": "string"}, "time_expression": {"type": "string"},
                            "description": {"type": "string"}
                        },
                        "required": ["type", "summary", "time_expression"]
                    }
                }, "required": ["event_details"]
            }
        }
    }
    return _call_gemini_api_with_retry(data)




# In gemini_service.py

def interpret_calendar_command(command_text):
    """Uses Gemini to extract intent and entities from a command."""
    prompt = f"""
    You are an AI assistant that extracts entities from a user's calendar command.
    Extract the user's intent ("create", "delete", "update") and any relevant text phrases for the event.

    RULES:
    - The current date is: {datetime.now().strftime('%Y-%m-%d')}
    - For "delete" or "update", "event_description" is the event to find.
    - For "create", "event_description" is the title of the new event.
    - For "create" or "update", "time_description" is the new time.
    - Respond ONLY with a JSON object.
    ---
    EXAMPLE:
    User Command: "create a meeting about the Q4 budget this Friday at noon"
    AI Response:
    {{
      "intent": "create",
      "event_description": "Meeting about the Q4 budget",
      "time_description": "this Friday at noon"
    }}
    ---
    ACTUAL TASK:
    User Command: "{command_text}"
    AI Response:
    """
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "event_description": {"type": "string"},
                    "time_description": {"type": "string"},
                    "error": {"type": "string"}
                },
                "required": ["intent", "event_description"]
            }
        }
    }
    structured_command = _call_gemini_api_with_retry(data)
    if not structured_command:
        return {"error": "Failed to interpret command after retries."}
    return structured_command