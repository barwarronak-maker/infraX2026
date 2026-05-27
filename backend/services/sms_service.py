"""
sms_service.py — Twilio SMS Integration
ROADSoS Emergency System

Sends a plain SMS alert as a fallback/additional channel alongside
WhatsApp and voice calls.
"""
import os
from twilio.rest import Client

ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")


def send_sms(to_number: str, message: str) -> str:
    """
    Send a plain SMS via Twilio Programmable Messaging.
    Returns the message SID on success.
    Raises RuntimeError if credentials are missing.
    """
    if not all([ACCOUNT_SID, AUTH_TOKEN, TWILIO_NUMBER]):
        raise RuntimeError(
            "Twilio credentials not set. Add TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER to environment."
        )

    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    # Truncate to 160 chars to stay within a single SMS segment
    body = message[:160]

    msg = client.messages.create(
        body=body,
        from_=TWILIO_NUMBER,
        to=to_number,
    )
    return msg.sid
