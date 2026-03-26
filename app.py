import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================
# CREDENTIALS (Set these in Render Env Vars)
# ============================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
VAPI_API_KEY = os.environ.get("VAPI_API_KEY")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID")
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

# In-memory storage for session tracking
call_sessions = {}

@app.route("/")
def home():
    return "Vapi Calling Backend: Online ✅"

@app.route("/health")
def health():
    return "OK", 200

# ============================================
# ROUTE: START THE CALL
# ============================================
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

    # ============================================
    # LANGUAGE-AWARE SYSTEM PROMPTS
    # ============================================
    language_instruction = (
        "\n\n## CRITICAL LANGUAGE RULES:\n"
        "1. DETECT the language the other person is speaking within their FIRST sentence.\n"
        "2. IMMEDIATELY switch to that SAME language for ALL your responses.\n"
        "3. If they speak Hindi, reply ONLY in Hindi.\n"
        "4. If they speak Tamil, reply in Tamil. Marathi → Marathi. Punjabi → Punjabi. Etc.\n"
        "5. If they mix Hindi and English (Hinglish), match that style.\n"
        "6. NEVER keep speaking English if the other person has switched to another language.\n"
        "7. Use natural, colloquial phrasing — not formal textbook translations.\n"
        "8. Your opening line is in English. After the FIRST reply from the other person, "
        "adapt to THEIR language completely.\n"
    )

    if is_confirmation:
        slot = details.get("slot_chosen", "the discussed time")
        opening_line = (
            f"Hello, I am calling back for {customer_name}. "
            f"We would like to confirm the slot for {slot}. Is that still available?"
        )
        system_prompt = (
            f"You are confirming a booking for {customer_name} at {business_name} for {slot}. "
            "Keep it brief and polite."
            + language_instruction
        )
    else:
        opening_line = (
            f"Hello, I'm calling for {customer_name} regarding a booking at {business_name}. "
            "Am I speaking with the right place?"
        )
        system_prompt = (
            f"You are a polite assistant calling on behalf of {customer_name}. "
            f"Goal: {goal}. Details: {details}. "
            "If the requested slot is taken, ask for 2-3 alternative available times. "
            "Once you have alternatives, say you will check with the customer and call back."
            + language_instruction
        )

    # ============================================
    # MULTILINGUAL VOICE — OpenAI (no extra API key needed)
    # ============================================
    voice_config = {
        "provider": "openai",
        "voiceId": "shimmer"
    }

    # ============================================
    # MULTILINGUAL TRANSCRIBER
    # ============================================
    transcriber_config = {
        "provider": "deepgram",
        "model": "nova-2",
        "language": "multi",
        "smartFormat": True,
        "languageDetectionEnabled": True
    }

    # ============================================
    # VAPI PAYLOAD
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
            "voice": voice_config,
            "transcriber": transcriber_config,
            "serverUrl": webhook_url,
            "silenceTimeoutSeconds": 15,
            "responseDelaySeconds": 0.5,
            "backchannelingEnabled": True,
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


# ============================================
# ROUTE: WEBHOOK FOR RESULTS
# ============================================
@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    data = request.json
    print(f"DEBUG WEBHOOK RAW: {data}")

    if not data:
        print("DEBUG WEBHOOK: received empty body")
        return "OK", 200

    if data.get("type") == "end-of-call-report":
        msg = data
    elif data.get("message", {}).get("type") == "end-of-call-report":
        msg = data.get("message", {})
    else:
        print(f"DEBUG WEBHOOK: not an end-of-call-report, ignoring.")
        return "OK", 200

    call_id = msg.get("call", {}).get("id")
    print(f"DEBUG WEBHOOK: call_id={call_id}, sessions={list(call_sessions.keys())}")

    session = call_sessions.get(call_id)
    if not session:
        print(f"DEBUG WEBHOOK: no session found for call_id={call_id}")
        return "OK", 200

    chat_id = session["chat_id"]
    transcript = msg.get("artifact", {}).get("transcript", "").strip()
    reason = msg.get("endedReason", "")
    t_low = transcript.lower()

    print(f"DEBUG WEBHOOK: endedReason={reason}, transcript length={len(transcript)}")

    if reason in ["customer-did-not-answer", "customer-busy", "voicemail"]:
        text = "🚫 *Business is not picking up calls.*\nPlease try again later."

    elif not transcript:
        text = (
            f"⚠️ *Call connected but no conversation recorded.*\n\n"
            f"Ended reason: `{reason}`\n\n"
            "This usually means the AI could not speak. Please try again with /start."
        )

    elif any(x in t_low for x in ["confirmed", "booked", "all set", "scheduled",
                                     "पक्का", "बुक", "कन्फर्म"]):
        text = f"✅ *Booking Confirmed!*\n\n*Transcript:*\n{transcript}"

    else:
        text = (
            f"⚠️ *Slot Filled*\n\nThe business suggested alternatives:\n\n"
            f"*Transcript:*\n{transcript}\n\n"
            "────────────────\n"
            "Reply with the *new time* for a confirmation call, or /exit."
        )

    if TELEGRAM_BOT_TOKEN:
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        tg_response = requests.post(
            tg_url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        )
        print(f"DEBUG WEBHOOK: Telegram response={tg_response.status_code}")

    if call_id in call_sessions:
        del call_sessions[call_id]

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
