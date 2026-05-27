import os, sys
sys.path.insert(0, '/Users/ronak/Desktop/ROADSoS/backend')
os.chdir('/Users/ronak/Desktop/ROADSoS/backend')
from dotenv import load_dotenv
load_dotenv('/Users/ronak/Desktop/ROADSoS/backend/.env')
from services.whatsapp_service import send_whatsapp
from services.sms_service import send_sms

CONTACTS = ['+917232062340', '+916205958187']
WA_MSG = (
    "🚨 *EMERGENCY SOS ALERT*\n\n"
    "📍 Location: https://maps.google.com/?q=28.24339,75.66590\n"
    "🏥 Nearest Hospital: Payal Hospital (0.61km away)\n"
    "📞 Coordinates: 28.24339, 75.66590\n\n"
    "_Sent via ROADSoS Emergency System_"
)
SMS_MSG = "SOS ALERT - ROADSoS Emergency. Location: https://maps.google.com/?q=28.24339,75.66590. Hospital: Payal Hospital (0.61km)."

print("=== WhatsApp ===")
for num in CONTACTS:
    try:
        sid = send_whatsapp(num, WA_MSG)
        print(f"  ✅ {num} -> {sid}")
    except Exception as e:
        err = str(e)
        if 'not currently registered' in err or 'sandbox' in err.lower():
            print(f"  ⚠️  {num} -> NOT joined sandbox. Send 'join receive-attention' to +14155238886 on WhatsApp")
        else:
            print(f"  ❌ {num} -> {err}")

print("\n=== SMS ===")
for num in CONTACTS:
    try:
        sid = send_sms(num, SMS_MSG)
        print(f"  ✅ {num} -> {sid}")
    except Exception as e:
        err = str(e)
        if 'unverified' in err.lower():
            print(f"  ⚠️  {num} -> Unverified for Twilio trial SMS. Verify at twilio.com/user/account/phone-numbers/verified")
        else:
            print(f"  ❌ {num} -> {err}")
