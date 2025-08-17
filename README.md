# GmailManager

This project is a Flask-based Gmail and Google Calendar manager with Gemini AI-powered email classification.

## Features

- **Google OAuth2 Login:** Securely log in with your Gmail account.
- **List Emails:** View your latest emails from Gmail.
- **Classify Emails:** Use Gemini API to categorize emails as Urgent, To Respond, FYI, or Meeting, with confidence scores and reasons.
- **Google Calendar Integration:** List and add events to your Google Calendar.

## Setup

1. **Clone the repository**
   ```
   git clone <your-repo-url>
   cd GmailManager
   ```

2. **Configure environment variables**
   - Create a `.env` file in the project folder:
     ```
     GMAIL_CLIENT_ID=your_gmail_client_id
     GMAIL_CLIENT_SECRET=your_gmail_client_secret
     GMAIL_REFRESH_TOKEN=your_gmail_refresh_token
     GMAIL_REDIRECT_URI=http://localhost:5000/callback
     EMAIL_ADDRESS=your_email_address@gmail.com
     GEMINI_API_KEY=your_gemini_api_key
     PUBSUB_TOPIC=your_pubsub_topic
     PUBSUB_VERIFICATION_TOKEN=your_pubsub_verification_token
     ```

3. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```

4. **Enable Gmail and Calendar APIs**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Enable Gmail API and Calendar API for your project.

5. **Run the Flask app**
   ```
   python Oauth.py
   ```

6. **Access the app**
   - Open [http://localhost:5000](http://localhost:5000) in your browser.

## Gemini Email Classification

- Use `gemini_email_classifier.py` to classify emails.
- You can use sample emails or fetch real emails from Gmail (requires a valid access token).
- The output includes category, confidence score, and reason for each email.

## Example Usage

```python
emails = [
    {
        "subject": "Urgent: Server Down",
        "snippet": "The production server is down. Please fix ASAP."
    },
    # ... more emails ...
]
result = classify_emails_with_gemini(emails)
for email in result:
    print(email)
```

## Notes

- Access tokens expire after 1 hour. Implement token refreshing for production use.
- Keep your `.env` file secure and never share your API keys or secrets publicly.

