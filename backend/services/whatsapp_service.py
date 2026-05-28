"""
whatsapp_service.py — Twilio WhatsApp Integration
ROADSoS Emergency System
"""
import os
from twilio.rest import Client

ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
# Use env var; default to the Twilio sandbox number for hackathon demo
FROM_WHATSAPP = os.getenv("FROM_WHATSAPP", "whatsapp:+14155238886")


def send_whatsapp(to_number: str, message: str) -> str:
    """
    Send a WhatsApp message via Twilio.
    Raises RuntimeError if credentials are not configured.
    """
    if not all([ACCOUNT_SID, AUTH_TOKEN]):
        raise RuntimeError(
            "Twilio credentials not set. "
            "Add TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to environment variables."
        )

    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    # Ensure the destination number has the whatsapp: prefix
    to = f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number

    try:
        msg = client.messages.create(
            body=message,
            from_=FROM_WHATSAPP,
            to=to,
        )
        return msg.sid
    except Exception as e:
        raise RuntimeError(f"WhatsApp send failed for {to_number}: {e}")