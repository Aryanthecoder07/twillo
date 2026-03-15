import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================
# CREDENTIALS & SETUP
# ============================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
BASE_URL = os.environ.get("BASE_URL", "https://twillo-i353.onrender.com")
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

    # The AI introduces itself and immediately states the request.
    opening_line = f"Hello, I am calling regarding a {goal.lower()} for {customer_name}. Am I speaking with {business_name}?"

    # REFINED SYSTEM PROMPT: Includes logic to ask for free slots if the primary is booked.
    system_prompt = f"""
    You are a polite, professional AI assistant calling {business_name} for {customer_name}.
    GOAL: {goal}.
    SPECIFIC REQUEST: {details}.
    
    STRATEGY:
    1. Confirm you are speaking with the right business.
    2. Ask for the specific date/time/service mentioned in the SPECIFIC REQUEST.
    3. IF THE SLOT IS TAKEN: Do not end the call yet. Say: "I see. Since that time is booked, could you tell me what other slots you have available for this?"
    4. GATHER INFO: Try to get at least 2-3 alternative free times from them.
    5. WRAP UP: Once you have the alternative times, say: "Thank you, I will check these times with {customer_name} and we will call back to confirm."
    
    RULES:
    - Keep responses very short (1-2 sentences).
    - If the user speaks Hindi/Hinglish, switch and reply in natural Hindi/Hinglish.
    - Do not repeat your introduction.
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
                "temperature": 0.5 # Lowered for better focus during negotiation
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "bIHbv24MWmeRgasZH58o" 
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
            
            # DETECT SUCCESS OR NEGOTIATION
            t_lower = transcript.lower()
            success_keywords = ["confirmed", "booked", "all set", "appointment is scheduled", "see you then"]
            
            if any(word in t_lower for word in success_keywords):
                header = "✅ **Booking Confirmed!**"
                instruction = "Your request was successful."
            else:
                header = "⚠️ **Slot Unavailable**"
                instruction = "The requested time was taken. See the available slots mentioned in the transcript below to rebook."

            summary = (
                f"{header}\n\n"
                f"{instruction}\n\n"
                f"**Transcript:**\n{transcript}\n\n"
                "────────────────\n🔄 Send /start to book a new free slot."
            )

            if TELEGRAM_BOT_TOKEN:
                telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(telegram_url, json={"chat_id": chat_id, "text": summary})
                
            if vapi_call_id in call_sessions:
                del call_sessions[vapi_call_id]

    return "OK", 200

if __name__ == "__main__":
    # Note: Render uses the PORT environment variable
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
