import os
import json
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Key Variables ---
# Your API key should be stored in a .env file for security.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Using the gemini-2.5-pro model for a single-prompt, multi-task request.
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"

def process_single_email_with_gemini(email):
    """
    Classifies, summarizes, extracts important terms, and generates a response draft from a single email.

    Args:
        email (dict): A dictionary containing 'subject', 'sender', and 'body' of the email.

    Returns:
        dict: A dictionary with the processed email data, including all new fields,
              or None if an error occurs.
    """
    
    # The prompt is updated to ask for all four tasks at once.
    prompt = (
        "You are an email assistant. For the following email, perform four tasks:\n"
        "1. Classify it as one of these categories: Urgent, To Respond, FYI, Meeting.\n"
        "2. Provide a brief summary of the email.\n"
        "3. Identify and list the most important terms or keywords from the email body.\n"
        "4. Generate a concise and professional response draft for the sender based on the email's content.\n\n"
        "For the email provided, return a JSON object with these fields:\n"
        "- subject\n"
        "- sender\n"
        "- body\n"
        "- category (one of: Urgent, To Respond, FYI, Meeting)\n"
        "- confidence (a number between 0 and 1, e.g., 0.92, showing confidence in the category)\n"
        "- reason (a short explanation for the category)\n"
        "- summary (a brief summary of the email)\n"
        "- important_terms (a list of keywords or important phrases)\n"
        "- response_draft (a professional response draft)\n\n"
        "Respond ONLY with a JSON object, no extra text or markdown.\n\n"
        "Email Details:\n"
        f"Subject: {email['subject']}\n"
        f"Sender: {email['sender']}\n"
        f"Body: {email['body']}\n"
    )

    # --- API Request Payload ---
    data = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            # This forces the API to return a clean JSON object, making parsing reliable.
            "responseMimeType": "application/json"
        }
    }
    
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=data)
        # Raises an error for bad status codes (4xx or 5xx)
        response.raise_for_status() 
        
        # Because we set responseMimeType, we can directly parse the response text as JSON.
        # The result from the API is now a single JSON object.
        return json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])

    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        print("Response body:", response.text)
        return None
    except Exception as e:
        print(f"An unexpected error occurred during API call or parsing: {e}")
        return None

# The Gmail fetching function remains the same, it is not modified.
def fetch_latest_emails_from_gmail(access_token, n=4):
    """Fetch the latest n emails with subject and snippet using Gmail API."""
    # (This function is unchanged)
    pass 

# --- Main Execution Block ---
if __name__ == "__main__":
    # Sample single email to process
    email_to_process = {
        "subject": "Urgent: System outage and recovery plan",
        "sender": "it_support@example.com",
        "body": "Hi Team, \n\nWe are experiencing a major system outage affecting the main production server. Our engineering team is currently investigating the root cause. We have initiated the recovery plan and expect a full restoration within the next 2-3 hours. The critical terms are **system outage**, **recovery plan**, and **production server**. Please hold all non-essential activities until further notice. \n\nThanks,\nIT Support"
    }
    
    result = process_single_email_with_gemini(email_to_process)
    
    if result:
        print("--- Email Processing Results ---")
        print(f"Subject: {result['subject']}")
        print(f"Sender: {result['sender']}")
        print(f"Category: {result['category']} (Confidence: {result['confidence']:.2f})")
        print(f"Reason: {result['reason']}")
        print(f"Summary: {result['summary']}")
        print(f"Important Terms: {', '.join(result['important_terms'])}")
        print("\n--- Generated Response Draft ---")
        print(result['response_draft'])
        print("------------------------------------")
