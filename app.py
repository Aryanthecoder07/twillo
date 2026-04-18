import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
VAPI_API_KEY = os.environ.get("VAPI_API_KEY")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

call_sessions = {}


@app.route("/")
def home():
    return "Vapi Calling Backend: Online ✅"


@app.route("/health")
def health():
    return "OK", 200


# ============================================
# DIAGNOSTIC TEST CALL — NO WEBHOOK AT ALL
# ============================================
@app.route("/test-call", methods=["POST"])
def test_call():
    data = request.json
    phone_number = data.get("phone") if data else None

    if not phone_number:
        return jsonify({"error": "Send {\"phone\": \"+91XXXXXXXXXX\"}"}), 400

    vapi_payload = {
        "assistant": {
            "firstMessage": "Hello! This is a test call. Can you hear me clearly? Please say yes or no.",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are making a quick test call. Greet the person. Ask if they can hear you. "
                            "If an IVR answers, choose English if available and try to reach a human, then say goodbye.\n\n"
                            "IVR / DIALPAD RULES (VERY IMPORTANT):\n"
                            "- If you hear an automated menu (IVR), do NOT keep talking over it. Navigate the menu.\n"
                            "- If there is a language choice and English is an option, ALWAYS choose English.\n"
                            " Example: \"Press 1 for Hindi, Press 2 for English\" -> press 2 using the dtmf tool.\n"
                            "- After choosing English, try to reach a human agent.\n"
                            "- Prefer these options in order:\n"
                            " 1) If the IVR explicitly says \"bookings\"/\"reservations\", press that.\n"
                            " 2) If it says \"agent/representative/operator\", press that.\n"
                            " 3) Otherwise press 0 for operator if offered/commonly accepted.\n"
                            "- If the IVR is still talking, WAIT silently until it finishes, then press keys.\n"
                            "- After pressing a key, WAIT for the next prompt before speaking again.\n"
                        )
                    }
                ],
                "temperature": 0.3,
                "tools": [
                    {"type": "dtmf"}
                ],
            },
            "voice": {
                "provider": "openai",
                "voiceId": "verse"
            },
            "silenceTimeoutSeconds": 30,
            "maxDurationSeconds": 60
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {
            "number": phone_number
        }
    }

    try:
        response = requests.post(
            "https://api.vapi.ai/call/phone",
            headers={
                "Authorization": f"Bearer {VAPI_API_KEY}",
                "Content-Type": "application/json"
            },
            json=vapi_payload,
            timeout=20
        )
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================
# AI TRANSCRIPT ANALYZER (GROQ — FREE)
# ============================================
def analyze_transcript(transcript):
    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY not set")
        return "UNKNOWN", "Could not analyze — missing API key.", ""

    prompt = f"""You are analyzing a phone call transcript between an AI assistant and a business.
The AI was calling to make or confirm a booking.

TRANSCRIPT:
{transcript}

Based on this transcript, answer these 3 things in EXACTLY this format:

STATUS: <one of: CONFIRMED / REJECTED / ALTERNATIVES_OFFERED / NO_CLEAR_OUTCOME>
SUMMARY: <1-2 sentence summary of what happened in the call, in English>
ALTERNATIVES: <if any alternative times/slots were offered, list them. Otherwise write NONE>

Rules:
- If the business said yes/okay/available/confirmed in ANY language → STATUS: CONFIRMED
- If the business said no/not available/full and gave other options → STATUS: ALTERNATIVES_OFFERED
- If the business flatly refused with no alternatives → STATUS: REJECTED
- If the conversation was unclear or got cut off → STATUS: NO_CLEAR_OUTCOME
- Understand Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Punjabi, Gujarati, Urdu and their transliterations
- Even if transcript is garbled or mixed language, try your best to understand the intent
"""

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0
            },
            timeout=15
        )

        if response.status_code == 200:
            result = response.json()["choices"][0]["message"]["content"].strip()
            status, summary, alternatives = "UNKNOWN", "", ""

            for line in result.split("\n"):
                line = line.strip()
                if line.upper().startswith("STATUS:"):
                    status = line.split(":", 1)[1].strip().upper()
                elif line.upper().startswith("SUMMARY:"):
                    summary = line.split(":", 1)[1].strip()
                elif line.upper().startswith("ALTERNATIVES:"):
                    alternatives = line.split(":", 1)[1].strip()

            return status, summary, alternatives
        else:
            return "UNKNOWN", "AI analysis failed.", ""

    except Exception as e:
        return "UNKNOWN", "AI analysis failed.", ""


# ============================================
# START CALL ENDPOINT
# ============================================
@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.json
    if not data:
        return jsonify({"error": "No data received"}), 400

    if not BASE_URL or not BASE_URL.startswith("https://"):
        return jsonify({"error": "BASE_URL env var not set correctly on Render."}), 500

    phone_number = data.get("phone")
    chat_id = data.get("chat_id")
    business_name = data.get("business_name", "the business")
    goal = data.get("goal", "make an inquiry")
    details = data.get("details", {}) or {}
    customer_name = details.get("customer_name", "a customer")

    webhook_url = f"{BASE_URL}/vapi-webhook"
    is_confirmation = "confirm" in str(goal).lower()

    ivr_rules = """
IVR / DIALPAD RULES (VERY IMPORTANT):
- If you hear an automated menu (IVR), do NOT keep explaining the request. Navigate the menu.
- If there is a language choice and English is an option, ALWAYS choose English.
 Example: "Press 1 for Hindi, Press 2 for English" -> press 2 using the dtmf tool.
- After choosing English, try to reach a human agent for bookings/reservations.
- Prefer these options in order:
 1) If the IVR explicitly says "bookings" or "reservations", press that option.
 2) If it says "talk to agent/representative/operator", press that option.
 3) Otherwise press 0 for operator if offered/commonly accepted.
- If the IVR is still talking, WAIT silently until it finishes, then press keys.
- After pressing a key, WAIT for the next prompt before speaking again.
"""

    if is_confirmation:
        slot = details.get("slot_chosen", "the discussed time")
        opening_line = (
            f"Hello, I am calling back for {customer_name}. "
            f"We would like to confirm the slot for {slot}. Is that still available?"
        )
        system_prompt = (
            f"You are confirming a booking for {customer_name} at {business_name} for {slot}.\n\n"
            "RULES:\n"
            "- Be brief and polite. Confirm availability clearly.\n"
            "- If the slot is not available, ask for 2-3 alternatives and say you will check with the customer.\n"
            "- ALWAYS speak your opening message immediately when someone answers.\n"
            "- If someone says hello or greets you, RESPOND immediately.\n"
            "- Match the language the other person speaks (Hindi, Tamil, Telugu, etc.).\n"
            "- Use natural colloquial phrasing.\n"
            "- If put on hold, wait silently until a person speaks, then greet them.\n"
            "- If silence lasts 20 seconds, say 'Hello, are you there?' once, then wait.\n"
            "- Never hang up because of a pause, hold music, or silence.\n"
            f"{ivr_rules}"
        )
    else:
        opening_line = (
            f"Hello, I'm calling for {customer_name} regarding a booking at {business_name}. "
            "Am I speaking with the right place?"
        )
        system_prompt = (
            f"You are a polite phone assistant calling on behalf of {customer_name}.\n"
            f"Calling: {business_name}\n"
            f"Goal: {goal}\n"
            f"Details: {details}\n\n"
            "RULES:\n"
            "- ALWAYS speak your opening message immediately when someone answers.\n"
            "- If someone says hello or greets you, RESPOND immediately.\n"
            "- If the requested slot is taken, ask for 2-3 alternatives.\n"
            "- Once you have alternatives, say you will check with the customer and call back.\n"
            "- Match the language the other person speaks (Hindi, Tamil, Telugu, etc.).\n"
            "- Use natural colloquial phrasing, not textbook translations.\n"
            "- If put on hold, wait silently until a person speaks, then greet them.\n"
            "- If silence lasts 20 seconds, say 'Hello, are you there?' once, then wait.\n"
            "- Never hang up because of a pause, hold music, or silence.\n"
            "- Be concise, natural, and human-like.\n"
            f"{ivr_rules}"
        )

    vapi_payload = {
        "assistant": {
            "firstMessage": opening_line,
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [{"role": "system", "content": system_prompt}],
                "temperature": 0.3,
                "tools": [{"type": "dtmf"}]
            },
            "voice": {"provider": "vapi", "voiceId": "Layla"},
            "serverUrl": webhook_url,
            "silenceTimeoutSeconds": 60,
            "maxDurationSeconds": 600,
            "responseDelaySeconds": 0.5,
            "numWordsToInterruptAssistant": 5
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {"number": phone_number}
    }

    try:
        response = requests.post(
            "https://api.vapi.ai/call/phone",
            headers={"Authorization": f"Bearer {VAPI_API_KEY}", "Content-Type": "application/json"},
            json=vapi_payload,
            timeout=20
        )
        if response.status_code == 201:
            call_id = response.json().get("id")
            call_sessions[call_id] = {"chat_id": chat_id, "phone": phone_number}
            return jsonify({"status": "calling", "call_id": call_id})
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================
# VAPI WEBHOOK — HANDLES ALL EVENT TYPES
# ============================================
@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    data = request.json
    if not data:
        return jsonify({}), 200

    event_type = data.get("type") or data.get("message", {}).get("type", "")

    if event_type == "end-of-call-report":
        msg = data if data.get("type") == "end-of-call-report" else data.get("message", {})
        call_id = msg.get("call", {}).get("id")
        session = call_sessions.get(call_id)
        if not session:
            return jsonify({}), 200

        chat_id = session.get("chat_id")
        transcript = (msg.get("artifact", {}) or {}).get("transcript", "") or ""
        reason = msg.get("endedReason", "")

        if reason in ["customer-did-not-answer", "customer-busy", "voicemail"]:
            text = "🚫 *Business is not picking up calls.*"
        elif not transcript:
            text = "⚠️ *Call connected but no conversation recorded.*"
        else:
            status, summary, alternatives = analyze_transcript(transcript)
            text = f"📞 *Call Completed*\nStatus: {status}\nSummary: {summary}"

        if TELEGRAM_BOT_TOKEN and chat_id:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            )
        if call_id in call_sessions:
            del call_sessions[call_id]

    return jsonify({}), 200


# ============================================
# RUN SERVER
# ============================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
