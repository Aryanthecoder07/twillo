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

# 3. Vapi Credentials (from Vapi Dashboard)
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
# ROUTE 2: START THE CALL
# ============================================
@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.json
    
    phone_number = data.get("phone")
    chat_id = data.get("chat_id")
    business_name = data.get("business_type", "the place")
    goal = data.get("goal", "make an inquiry")
    details = data.get("details", {})
    customer_name = details.get("customer_name", "a customer")

    # The goal is passed from call_agent.py (e.g., "haircut appointment" or "table booking")
    # This opening line ensures the AI states the reason for calling immediately.
    opening_line = f"Hello, I am calling regarding a {goal.lower()} for {customer_name}. Am I speaking with {business_name}?"

    # The System Prompt is now more concise to prevent repetition and handle multilingual needs.
    system_prompt = f"""
    You are a polite, professional AI assistant calling {business_name}.
    Your specific goal is: {goal}.
    Information to provide: {details}.
    
    RULES:
    1. Confirm you are speaking with the right business first.
    2. Once confirmed, provide the booking details (date, time, service) immediately.
    3. Keep responses very short (1-2 sentences max).
    4. LANGUAGE MIRRORING: If the user speaks Hindi or Hinglish, switch and reply in natural Hindi/Hinglish.
    5. When the goal is achieved (e.g., appointment booked), say goodbye and end the call.
    6. Do not repeat your opening introduction once the conversation moves forward.
    """

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
                "messages": [{"role": "system", "content": system_prompt}],
                "temperature": 0.7
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "bIHbv24MWmeRgasZH58o" # Premium multilingual voice
            },
            "serverUrl": f"{BASE_URL}/vapi-webhook" 
        }
    }

    try:
        response = requests.post(
            "https://api.vapi.ai/call/phone",
            headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
            json=vapi_payload,
            timeout=30
        )
        response_data = response.json()

        if response.status_code == 201:
            vapi_call_id = response_data.get("id")
            # Save session for the webhook
            call_sessions[vapi_call_id] = {"chat_id": chat_id}
            return jsonify({"status": "calling", "call_sid": vapi_call_id})
        else:
            print(f"🚨 Vapi API Error: {response_data}", flush=True)
            return jsonify({"error": "Failed to start Vapi call"}), 500

    except Exception as e:
        print(f"🚨 Connection Error: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


# ============================================
# ROUTE 3: VAPI WEBHOOK (The Final Receipt)
# ============================================
@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    data = request.json
    message_data = data.get("message", {})
    
    if message_data.get("type") == "end-of-call-report":
        vapi_call_id = message_data.get("call", {}).get("id")
        session = call_sessions.get(vapi_call_id)
        
        if session:
            chat_id = session["chat_id"]
            transcript = message_data.get("artifact", {}).get("transcript", "No transcript available.")
            
            # Simple confirmation detection for the Telegram header
            t_lower = transcript.lower()
            if any(word in t_lower for word in ["confirm", "booked", "appointment set", "thank you"]):
                header = "✅ **Booking Confirmed!**"
            else:
                header = "📞 **Call Finished**"

            summary = f"{header}\n\n**Transcript:**\n\n{transcript}\n\n"
            summary += "────────────────\n🔄 Send /start for a new request."

            if TELEGRAM_BOT_TOKEN:
                telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(telegram_url, json={"chat_id": chat_id, "text": summary})
                
            # Clean up memory
            if vapi_call_id in call_sessions:
                del call_sessions[vapi_call_id]

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
