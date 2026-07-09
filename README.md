# Feedback Analysis Workflow

This project automates the processing of customer feedback emails from Gmail. It extracts the email content, analyzes sentiment using OpenAI's GPT model, stores the results in a SQLite database, and sends real‑time alerts (Slack/email) when negative feedback is detected.

The workflow follows the exact process shown in the provided diagram:

1. **Trigger** – listens for new emails under a specified Gmail label.
2. **Extract Feedback Data** – retrieves sender, subject, and body from each unread email.
3. **Analyze Sentiment** – sends the text to OpenAI with a structured prompt.
4. **Check Sentiment** – classifies as positive, neutral, or negative with a score.
5. **Store in Feedback Database** – logs every feedback entry with sentiment and timestamp.
6. **Alert Team on Negative Feedback** – sends notifications via Slack, email, or both.
7. **Execute workflow** – runs continuously in a polling loop.

---

## Features

- ✅ **Gmail integration** – uses Gmail API to monitor a specific label.
- ✅ **AI‑powered sentiment** – leverages OpenAI's GPT (e.g., `gpt-3.5-turbo`) for accurate classification and score.
- ✅ **Persistent storage** – SQLite database stores all feedback for historical analysis.
- ✅ **Real‑time alerts** – notifies your team instantly when negative feedback arrives.
- ✅ **Modular design** – easy to extend or replace components (e.g., use another LLM, add more alert channels).

---

## Prerequisites

- Python 3.8+
- A Google Cloud project with Gmail API enabled
- OAuth 2.0 credentials (`credentials.json`) for Gmail
- An OpenAI API key
- (Optional) Slack webhook URL and/or SMTP credentials for email alerts

---

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/yourusername/feedback-workflow.git
cd feedback-workflow
pip install -r requirements.txt
