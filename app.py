import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================
# CREDENTIALS & SETUP
# ============================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
BASE_URL = os.environ.get("BASE_URL") 
VAPI_API_KEY = os.environ.get("VAPI_API_KEY")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID")

call_sessions = {}

@app.route("/")
def home():
    return "AI Multi-Service Backend Running ✅"

@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.json
    phone_number = data.get("phone")
    chat_id = data.get("chat_id")
    business_name = data.get("business_name", "the business")
    goal = data.get("goal", "make an inquiry")
    details = data.get("details", {})
    customer_name = details.get("customer_name", "a customer")

    # Detect if this is a follow-up Confirmation Call
    is_confirmation = "confirm" in goal.lower()

    if is_confirmation:
        slot = details.get("slot_chosen", "the discussed time")
        opening_line = f"Hello, I am calling back for {customer_name}. We would like to confirm the slot for {slot} that we just discussed. Is that still okay?"
        system_prompt = f"You are confirming a booking for {customer_name} at {business_name} for the time: {slot}. If they say yes, say thank you and goodbye. If no, ask for one more time and end."
    else:
        opening_line = f"Hello, I am calling for {customer_name} regarding a {goal} for {business_name}. Am I speaking with the right person?"
        system_prompt = f"""
        You are a polite AI assistant calling {business_name} for {customer_name}.
        GOAL: {goal}. DETAILS: {details}.
        STRATEGY:
        1. Ask for the specific slot in DETAILS.
        2. IF TAKEN: Say: 'I see. Since that is booked, what other slots are available?'
        3. GATHER INFO: Get alternative times, then say: 'I will check with {customer_name} and call back to confirm.'
        4. Switch to Hindi/Hinglish if they do.
        """

    vapi_payload = {
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {"number": phone_number},
        "assistant": {
            "firstMessage": opening_line,
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [{"role": "system", "content": system_prompt}]
            },
            "serverUrl": f"{BASE_URL}/vapi-webhook" 
        }
    }

    try:
        response = requests.post(
            "https://api.vapi.ai/call/phone",
            headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
            json=vapi_payload
        )
        if response.status_code == 201:
            call_id = response.json().get("id")
            # Store data to remember this session in the webhook
            call_sessions[call_id] = {
                "chat_id": chat_id, 
                "phone": phone_number, 
                "business_name": business_name,
                "customer_name": customer_name
            }
            return jsonify({"status": "calling", "call_id": call_id})
        return jsonify({"error": "Vapi Error"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    data = request.json
    msg = data.get("message", {})
    
    if msg.get("type") == "end-of-call-report":
        call_id = msg.get("call", {}).get("id")
        session = call_sessions.get(call_id)
        if not session: return "OK", 200

        chat_id = session["chat_id"]
        transcript = msg.get("artifact", {}).get("transcript", "No transcript available.")
        reason = msg.get("endedReason")
        t_low = transcript.lower()

        # Outcome 1: NO ANSWER
        if reason in ["customer-did-not-answer", "customer-busy", "voicemail"]:
            text = "🚫 **Business is not picking up calls.**\nPlease try again later."
        
        # Outcome 2: CONFIRMED
        elif any(x in t_low for x in ["confirmed", "booked", "all set", "scheduled"]):
            text = f"✅ **Booking Confirmed!**\n\n**Transcript:**\n{transcript}"

        # Outcome 3: SLOT FILLED / ALTERNATIVES
        else:
            text = (f"⚠️ **Slot Filled**\n\nThe business suggested these alternatives:\n\n"
                    f"**Transcript:**\n{transcript}\n\n"
                    "────────────────\n"
                    "1. Type the **new time** to send a confirmation call.\n"
                    "2. Send /exit to cancel.")

        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                      json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
        
        if call_id in call_sessions: del call_sessions[call_id]

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
