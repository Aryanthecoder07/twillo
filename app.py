import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================
# CREDENTIALS & SETUP
# ============================================
# 1. Telegram Token for sending the final receipt
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 

# 2. Your Render URL (Used so Vapi knows where to send the transcript)
BASE_URL = os.environ.get("BASE_URL", "https://twillo-i353.onrender.com")

# 3. Vapi Credentials (You will get these from the Vapi Dashboard)
VAPI_API_KEY = os.environ.get("VAPI_API_KEY")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID")

# In-memory storage to match Vapi Calls to Telegram Users
call_sessions = {}

# ============================================
# ROUTE 1: ROOT (Keep-Alive)
# ============================================
@app.route("/")
def home():
    return "Vapi AI Calling Backend Running ✅"

# ============================================
# ROUTE 2: START THE CALL (Triggered by bot.py)
# ============================================
@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.json
    
    phone_number = data.get("phone")
    chat_id = data.get("chat_id")
    business_type = data.get("business_type", "Business")
    goal = data.get("goal", "make an inquiry")
    details = data.get("details", {})

    customer_name = details.get("customer_name", "a customer")
    opening_line = f"Hello, I am calling regarding {business_type.lower()}. My name is {customer_name}."

    # The "Chameleon" Prompt - Instructs Vapi to mirror the user's language (Hindi/English)
    system_prompt = f"""
    You are a polite, highly intelligent, multilingual AI assistant calling a {business_type}.
    Your goal is: {goal}.
    Here are the details you MUST provide if asked: {details}.
    
    RULES:
    1. Keep responses very short and conversational (1-2 sentences max).
    2. Speak naturally like a human.
    3. LANGUAGE MIRRORING: You must ALWAYS reply in the exact same language the user is speaking. 
       If they speak English, reply in English. If they speak Hindi or Hinglish, instantly switch and reply in natural Hindi/Hinglish.
    4. When the goal is completely achieved, politely say goodbye and end the call.
    """

    # Build the request for Vapi
    vapi_payload = {
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {
            "number": phone_number
        },
        "assistant": {
            "name": "Booking Assistant",
            "firstMessage": opening_line,
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [{"role": "system", "content": system_prompt}]
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "bIHbv24MWmeRgasZH58o" # A premium multilingual voice from ElevenLabs
            },
            # Tell Vapi where to send the final transcript when they hang up!
            "serverUrl": f"{BASE_URL}/vapi-webhook" 
        }
    }

    try:
        # Send the command to Vapi!
        response = requests.post(
            "https://api.vapi.ai/call/phone",
            headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
            json=vapi_payload,
            timeout=30
        )
        response_data = response.json()

        # 201 Created means Vapi accepted the call successfully
        if response.status_code == 201:
            vapi_call_id = response_data.get("id")
            
            # Save the Chat ID so we know who to text when the call ends
            call_sessions[vapi_call_id] = {"chat_id": chat_id}
            
            return jsonify({"status": "calling", "call_sid": vapi_call_id})
        else:
            print(f"🚨 Vapi API Error: {response_data}", flush=True)
            return jsonify({"error": "Failed to start Vapi call"}), 500

    except Exception as e:
        print(f"🚨 Error starting call: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


# ============================================
# ROUTE 3: VAPI WEBHOOK (The Final Receipt)
# ============================================
@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    data = request.json
    
    # Vapi sends many background events, we only care when the call is completely over
    message_data = data.get("message", {})
    
    if message_data.get("type") == "end-of-call-report":
        vapi_call_id = message_data.get("call", {}).get("id")
        session = call_sessions.get(vapi_call_id)
        
        # If we don't have the chat_id saved, we can't send a Telegram message
        if not session or not session.get("chat_id"):
            return "OK", 200

        chat_id = session["chat_id"]
        
        # Grab the beautiful transcript Vapi generated
        transcript_text = message_data.get("artifact", {}).get("transcript", "No transcript available.")
        
        # 1. Quick check if the booking was successful
        transcript_lower = transcript_text.lower()
        if "confirm" in transcript_lower or "book" in transcript_lower or "thank" in transcript_lower:
            header = "✅ **Booking Confirmed!**"
        else:
            header = "❌ **Booking Failed or Cancelled.**"

        # 2. Build the final Telegram message
        summary = f"{header}\n\n**Call Transcript:**\n\n{transcript_text}\n\n"
        
        # 3. Add the final instructions
        summary += "────────────────\n"
        summary += "🔄 **Send /start to make a new booking!**"

        # Send it to Telegram!
        if TELEGRAM_BOT_TOKEN:
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(telegram_url, json={"chat_id": chat_id, "text": summary})
            
        # Clean up memory so the server doesn't get bloated
        del call_sessions[vapi_call_id]

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
