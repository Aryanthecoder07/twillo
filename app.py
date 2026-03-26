import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
VAPI_API_KEY = os.environ.get("VAPI_API_KEY")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID")
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

call_sessions = {}

@app.route("/")
def home():
    return "Vapi Calling Backend: Online ✅"

@app.route("/health")
def health():
    return "OK", 200

@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.json
    if not data:
        return jsonify({"error": "No data received"}), 400

    if not BASE_URL or not BASE_URL.startswith("https://"):
        print(f"ERROR: BASE_URL is invalid or missing: '{BASE_URL}'")
        return jsonify({"error": "BASE_URL env var not set correctly on Render."}), 500

    phone_number = data.get("phone")
    chat_id = data.get("chat_id")
    business_name = data.get("business_name", "the business")
    goal = data.get("goal", "make an inquiry")
    details = data.get("details", {})
    customer_name = details.get("customer_name", "a customer")

    webhook_url = f"{BASE_URL}/vapi-webhook"
    print(f"DEBUG: webhook_url = {webhook_url}")

    is_confirmation = "confirm" in str(goal).lower()

    language_instruction = (
        "\n\nCRITICAL LANGUAGE RULES: "
        "1. Detect the language the other person speaks in their first sentence. "
        "2. Immediately switch to that same language for all responses. "
        "3. If they speak Hindi, reply only in Hindi. "
        "4. If they mix Hindi-English, match that Hinglish style. "
        "5. Never keep speaking English if they switched to another language. "
        "6. Use natural colloquial phrasing, not textbook translations."
    )

    if is_confirmation:
        slot = details.get("slot_chosen", "the discussed time")
        opening_line = (
            f"Hello, I am calling back for {customer_name}. "
            f"We would like to confirm the slot for {slot}. Is that still available?"
        )
        system_prompt = (
            f"You are confirming a booking for {customer_name} at {business_name} for {slot}. "
            "Keep it brief." + language_instruction
        )
    else:
        opening_line = (
            f"Hello, I'm calling for {customer_name} regarding a booking at {business_name}. "
            "Am I speaking with the right place?"
        )
        system_prompt = (
            f"You are a polite assistant for {customer_name}. Goal: {goal}. Details: {details}. "
            "If the requested slot is taken, ask for 2-3 alternative available times. "
            "Once you have alternatives, say you will check with the customer and call back."
            + language_instruction
        )

    # ============================================
    # ONLY 2 CHANGES FROM YOUR ORIGINAL CODE:
    # 1. Voice changed to OpenAI shimmer
    # 2. Language instruction added to prompt
    # ============================================
    vapi_payload = {
        "assistant": {
            "firstMessage": opening_line,
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [{"role": "system", "content": system_prompt}],
                "temperature": 0.3
            },
            "voice": {
                "provider": "openai",
                "voiceId": "shimmer"
            },
            "serverUrl": webhook_url
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {
            "number": phone_number
        }
    }

    try:
        headers = {
            "Authorization": f"Bearer {VAPI_API_KEY}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            "https://api.vapi.ai/call/phone",
            headers=headers,
            json=vapi_payload,
            timeout=20
        )

        print(f"Vapi Status Code: {response.status_code}")
        print(f"Vapi Response JSON: {response.text}")

        if response.status_code == 201:
            res_data = response.json()
            call_id = res_data.get("id")
            call_sessions[call_id] = {"chat_id": chat_id, "phone": phone_number}
            print(f"DEBUG: Call started. call_id={call_id}, chat_id={chat_id}")
            return jsonify({"status": "calling", "call_id": call_id})
        else:
            return jsonify({
                "error": "Vapi Error",
                "vapi_response": response.json()
            }), response.status_code

    except Exception as e:
        print(f"Server Exception: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    data = request.json
    print(f"DEBUG WEBHOOK RAW: {data}")

    if not data:
        return "OK", 200

    if data.get("type") == "end-of-call-report":
        msg = data
    elif data.get("message", {}).get("type") == "end-of-call-report":
        msg = data.get("message", {})
    else:
        return "OK", 200

    call_id = msg.get("call", {}).get("id")
    session = call_sessions.get(call_id)
    if not session:
        return "OK", 200

    chat_id = session["chat_id"]
    transcript = msg.get("artifact", {}).get("transcript", "").strip()
    reason = msg.get("endedReason", "")
    t_low = transcript.lower()

    if reason in ["customer-did-not-answer", "customer-busy", "voicemail"]:
        text = "🚫 *Business is not picking up calls.*\nPlease try again later."
    elif not transcript:
        text = (
            f"⚠️ *Call connected but no conversation recorded.*\n\n"
            f"Ended reason: `{reason}`\n\n"
            "Please try again with /start."
        )
    elif any(x in t_low for x in ["confirmed", "booked", "all set", "scheduled"]):
        text = f"✅ *Booking Confirmed!*\n\n*Transcript:*\n{transcript}"
    else:
        text = (
            f"⚠️ *Slot Filled*\n\nAlternatives suggested:\n\n"
            f"*Transcript:*\n{transcript}\n\n"
            "Reply with *new time* or /exit."
        )

    if TELEGRAM_BOT_TOKEN:
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(tg_url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

    if call_id in call_sessions:
        del call_sessions[call_id]

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
