import os
import base64
import json
import sqlite3
import pickle
import re
import time
from datetime import datetime
from email.mime.text import MIMEText
import smtplib

import openai
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- Configuration ---
GMAIL_LABEL = "Feedback"          # Label to watch for new feedback
SENTIMENT_MODEL = "gpt-3.5-turbo" # or "gpt-4"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-openai-api-key")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "team@example.com")  # for email alerts
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# OpenAI client
openai.api_key = OPENAI_API_KEY

# --- Database setup ---
DB_FILE = "feedback.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            subject TEXT,
            body TEXT,
            sentiment TEXT,
            sentiment_score REAL,
            received_at TIMESTAMP,
            alert_sent BOOLEAN DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def store_feedback(sender, subject, body, sentiment, score):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO feedback (sender, subject, body, sentiment, sentiment_score, received_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (sender, subject, body, sentiment, score, datetime.utcnow()))
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id

def mark_alert_sent(feedback_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE feedback SET alert_sent = 1 WHERE id = ?', (feedback_id,))
    conn.commit()
    conn.close()

# --- Gmail API ---
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.modify']

def get_gmail_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return build('gmail', 'v1', credentials=creds)

def get_label_id(service, label_name):
    results = service.users().labels().list(userId='me').execute()
    labels = results.get('labels', [])
    for label in labels:
        if label['name'] == label_name:
            return label['id']
    # Create label if not exists
    label_obj = {
        'name': label_name,
        'labelListVisibility': 'labelShow',
        'messageListVisibility': 'show'
    }
    created = service.users().labels().create(userId='me', body=label_obj).execute()
    return created['id']

def fetch_unread_feedback(service, label_id):
    query = f"label:{label_id} is:unread"
    results = service.users().messages().list(userId='me', q=query).execute()
    messages = results.get('messages', [])
    return messages

def get_message_content(service, msg_id):
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    payload = msg.get('payload', {})
    headers = msg.get('payload', {}).get('headers', [])
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
    sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')

    parts = []
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data')
                if data:
                    text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    parts.append(text)
    else:
        data = payload['body'].get('data')
        if data:
            text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            parts.append(text)
    body = "\n".join(parts).strip()
    return sender, subject, body

def mark_as_read(service, msg_id):
    service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()

# --- Sentiment Analysis with OpenAI ---
def analyze_sentiment(text):
    prompt = (
        "Analyze the sentiment of the following customer feedback text. "
        "Respond only with a JSON object containing 'sentiment' (positive, neutral, or negative) "
        "and 'score' (a float between -1.0 and 1.0, where -1 is very negative and 1 is very positive).\n\n"
        f"Feedback: {text[:2000]}\n\nResponse:"
    )
    try:
        response = openai.ChatCompletion.create(
            model=SENTIMENT_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that analyzes sentiment."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=60
        )
        result_text = response.choices[0].message.content.strip()
        # Parse JSON from response (handle possible markdown)
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            sentiment = data.get('sentiment', 'neutral').lower()
            score = float(data.get('score', 0.0))
            return sentiment, score
        else:
            # fallback: check keywords
            if 'negative' in result_text.lower():
                return 'negative', -0.8
            elif 'positive' in result_text.lower():
                return 'positive', 0.8
            else:
                return 'neutral', 0.0
    except Exception as e:
        print(f"OpenAI error: {e}")
        return 'neutral', 0.0

# --- Alerting ---
def send_alert(feedback_id, sender, subject, body, sentiment, score):
    print(f"ALERT: Negative feedback detected (ID: {feedback_id}) from {sender}")

    # Slack alert
    if SLACK_WEBHOOK_URL:
        import requests
        message = {
            "text": f"🚨 *Negative Feedback Alert*\nFrom: {sender}\nSubject: {subject}\nSentiment Score: {score}\n\n{body[:500]}..."
        }
        try:
            requests.post(SLACK_WEBHOOK_URL, json=message)
        except Exception as e:
            print(f"Slack alert failed: {e}")

    # Email alert
    if SMTP_USER and SMTP_PASS:
        try:
            msg = MIMEText(f"Negative feedback received.\n\nFrom: {sender}\nSubject: {subject}\nScore: {score}\n\n{body}")
            msg['Subject'] = f"Negative Feedback Alert: {subject[:50]}"
            msg['From'] = SMTP_USER
            msg['To'] = ALERT_EMAIL
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        except Exception as e:
            print(f"Email alert failed: {e}")

# --- Main workflow ---
def process_feedback():
    init_db()
    service = get_gmail_service()
    label_id = get_label_id(service, GMAIL_LABEL)
    print(f"Watching label '{GMAIL_LABEL}' (ID: {label_id}) for new feedback...")

    while True:
        try:
            messages = fetch_unread_feedback(service, label_id)
            if not messages:
                print("No new feedback emails.")
            else:
                print(f"Found {len(messages)} new feedback emails.")
                for msg in messages:
                    msg_id = msg['id']
                    sender, subject, body = get_message_content(service, msg_id)
                    print(f"Processing from {sender}: {subject}")

                    # Analyze sentiment
                    sentiment, score = analyze_sentiment(body)
                    print(f"Sentiment: {sentiment} (score: {score})")

                    # Store in DB
                    feedback_id = store_feedback(sender, subject, body, sentiment, score)

                    # Alert if negative
                    if sentiment == 'negative':
                        send_alert(feedback_id, sender, subject, body, sentiment, score)
                        mark_alert_sent(feedback_id)

                    # Mark as read
                    mark_as_read(service, msg_id)

            # Wait before next check (poll every 60 seconds)
            time.sleep(60)
        except HttpError as error:
            print(f"Gmail API error: {error}")
            time.sleep(60)
        except Exception as e:
            print(f"Unexpected error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    process_feedback()