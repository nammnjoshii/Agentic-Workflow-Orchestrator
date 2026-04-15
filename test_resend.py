"""
Quick connectivity test for the Resend API key.
Uses Resend's built-in onboarding@resend.dev sender — no domain verification needed.

Usage:
    python3 test_resend.py
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
TO_EMAIL = "nammnjoshii09@gmail.com"

if not RESEND_API_KEY:
    print("ERROR: RESEND_API_KEY not set in .env")
    raise SystemExit(1)

resp = requests.post(
    "https://api.resend.com/emails",
    headers={
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    },
    json={
        "from": "onboarding@resend.dev",
        "to": [TO_EMAIL],
        "subject": "Hello World",
        "html": "<p>Congrats on sending your <strong>first email</strong>!</p>",
    },
    timeout=15,
)

if 200 <= resp.status_code < 300:
    print(f"SUCCESS ({resp.status_code}) — email sent to {TO_EMAIL}")
    print(f"Resend email ID: {resp.json().get('id')}")
else:
    print(f"FAILED ({resp.status_code}): {resp.text}")
