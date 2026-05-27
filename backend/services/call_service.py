"""
call_service.py — Twilio Voice Call Integration
ROADSoS Emergency System
"""
import os
from twilio.rest import Client

ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")


def make_call(to_number: str, message: str) -> str:
    """
    Place a voice call via Twilio TTS.
    Raises exception if Twilio credentials are not configured.
    """
    if not all([ACCOUNT_SID, AUTH_TOKEN, TWILIO_NUMBER]):
        raise RuntimeError(
            "Twilio credentials not set. Add TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER to environment."
        )

    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    # Sanitize message for TwiML (strip chars that break XML)
    safe_msg = message.replace("&", "and").replace("<", "").replace(">", "")

    call = client.calls.create(
        twiml=f"<Response><Say voice='alice'>{safe_msg}</Say></Response>",
        to=to_number,
        from_=TWILIO_NUMBER,
    )
    return call.sid
