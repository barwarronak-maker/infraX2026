"""
whatsapp_service.py — Twilio WhatsApp Integration
ROADSoS Emergency System
"""
import os
from twilio.rest import Client

ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN")
FROM_WHATSAPP = "whatsapp:+14155238886"  # Twilio sandbox number


def send_whatsapp(to_number: str, message: str) -> str:
    """
    Send a WhatsApp message via Twilio.
    Raises exception if Twilio credentials are not configured.
    """
    if not all([ACCOUNT_SID, AUTH_TOKEN]):
        raise RuntimeError(
            "Twilio credentials not set. Add TWILIO_ACCOUNT_SID and "
            "TWILIO_AUTH_TOKEN to environment."
        )

    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    # Ensure number has whatsapp: prefix
    to = f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number

    msg = client.messages.create(
        body=message,
        from_=FROM_WHATSAPP,
        to=to,
    )
    return msg.sid