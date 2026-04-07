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
# AI TRANSCRIPT ANALYZER (GROQ — FREE)
# ============================================
def analyze_transcript(transcript):
    """Send transcript to Groq LLaMA 3.1 8B and get verdict."""
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
            print(f"DEBUG GROQ ANALYSIS: {result}")

            status = "UNKNOWN"
            summary = ""
            alternatives = ""

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
            print(f"Groq Error: {response.status_code} {response.text}")
            return "UNKNOWN", "AI analysis failed.", ""

    except Exception as e:
        print(f"Groq Exception: {str(e)}")
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
    # CLEAN, CONSOLIDATED LANGUAGE INSTRUCTION
    # ============================================
    language_instruction = (
        "\n\nLANGUAGE RULES:\n"
        "- Detect the language the other person speaks in their FIRST sentence.\n"
        "- Immediately switch to that language for ALL your responses.\n"
        "- Hindi → reply in Hindi. Tamil → Tamil. Telugu → Telugu. Etc.\n"
        "- If they mix languages, match their style naturally.\n"
        "- Use natural colloquial phrasing, not textbook translations.\n"
        "- Exception: When interacting with IVR/automated systems, use English.\n"
    )

    # ============================================
    # CLEAN, CONSOLIDATED CALL BEHAVIOR INSTRUCTION
    # ============================================
    call_behavior_instruction = (
        "\n\nCALL BEHAVIOR RULES:\n"
        "- ALWAYS deliver your opening message as soon as someone answers.\n"
        "- If someone says 'hello', 'hi', or greets you — RESPOND immediately. They are a real person.\n"
        "- If you reach an IVR/automated system, try to connect to a human operator.\n"
        "- Choose options for: operator > reception > appointments > other.\n"
        "- For IVR menus that say 'press 1', 'press 2' etc., use the dtmf function to send keypad tones. NEVER say digits aloud.\n"
        "- After pressing a key, wait silently for the system to respond.\n"
        "- If the IVR asks for language, choose English.\n"
        "- Once a real human answers, switch to their language and resume normal conversation.\n"
    )

    # ============================================
    # CLEAN, CONSOLIDATED SILENCE/HOLD INSTRUCTION
    # ============================================
    silence_and_hold_instruction = (
        "\n\nSILENCE AND HOLD RULES:\n"
        "- When the call first connects, ALWAYS deliver your opening message immediately.\n"
        "- If someone says 'hello' or greets you, RESPOND — they are a real person.\n"
        "- Only go silent if you hear EXPLICIT hold phrases like 'please hold', "
        "'transferring you', 'connecting you', or hold music.\n"
        "- If on hold, wait silently. When a new voice speaks, greet them and state your purpose.\n"
        "- If there is dead silence for 20 seconds, say 'Hello, are you there?' ONCE.\n"
        "- After that one check, wait silently for another 40 seconds.\n"
        "- Consider the call dropped ONLY after 60 seconds of absolute dead silence.\n"
        "- Hold music or background noise means the call is active — wait silently.\n"
        "- NEVER say goodbye or hang up just because of a pause.\n"
    )

    # ============================================
    # BUILD SYSTEM PROMPT (CONFIRMATION vs NEW BOOKING)
    # ============================================
    if is_confirmation:
        slot = details.get("slot_chosen", "the discussed time")
        opening_line = (
            f"Hello, I am calling back for {customer_name}. "
            f"We would like to confirm the slot for {slot}. Is that still available?"
        )
        system_prompt = (
            f"You are confirming a booking for {customer_name} at {business_name} for {slot}.\n"
            "Keep it brief and polite. Confirm availability clearly.\n"
            "If the slot is not available, ask for 2-3 alternative available times "
            "and say you will check with the customer and call back."
            + language_instruction
            + call_behavior_instruction
            + silence_and_hold_instruction
        )
    else:
        opening_line = (
            f"Hello, I'm calling for {customer_name} regarding a booking at {business_name}. "
            "Am I speaking with the right place?"
        )
        system_prompt = (
            f"You are a polite phone assistant calling on behalf of {customer_name}.\n"
            f"You are calling {business_name}.\n"
            f"Goal: {goal}\n"
            f"Details: {details}\n\n"
            "If the requested slot is taken, ask for 2-3 alternative available times.\n"
            "Once you have alternatives, say you will check with the customer and call back.\n"
            "Be concise, natural, and human-like."
            + language_instruction
            + call_behavior_instruction
            + silence_and_hold_instruction
        )

    # ============================================
    # VAPI PAYLOAD — FIXED SETTINGS
    # ============================================
    vapi_payload = {
        "assistant": {
            "firstMessage": opening_line,
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    }
                ],
                "temperature": 0.3,
                "tools": [
                    {
                        "type": "dtmf"
                    }
                ]
            },
            "voice": {
                "provider": "openai",
                "voiceId": "sage"
            },
            "serverUrl": webhook_url,

            # ===== FIXED: PREVENT EARLY HANGUP WITHOUT SILENCING THE AI =====
            "silenceTimeoutSeconds": 60,
            "maxDurationSeconds": 600,
            "responseDelaySeconds": 0.5,
            "numWordsToInterruptAssistant": 5,
            "backgroundSound": "off",

            # Transport / ring timeout
            "transportConfigurations": [
                {
                    "provider": "twilio",
                    "timeout": 60,
                    "record": False
                }
            ]
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
            try:
                error_data = response.json()
            except Exception:
                error_data = {"raw": response.text}

            return jsonify({
                "error": "Vapi Error",
                "vapi_response": error_data
            }), response.status_code

    except Exception as e:
        print(f"Server Exception: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ============================================
# VAPI WEBHOOK — END OF CALL REPORT
# ============================================
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

    print(f"DEBUG WEBHOOK: endedReason={reason}, transcript={transcript}")

    if reason in ["customer-did-not-answer", "customer-busy", "voicemail"]:
        text = "🚫 *Business is not picking up calls.*\nPlease try again later."

    elif not transcript:
        text = (
            f"⚠️ *Call connected but no conversation recorded.*\n\n"
            f"Ended reason: `{reason}`\n\n"
            "Please try again with /start."
        )

    else:
        status, summary, alternatives = analyze_transcript(transcript)

        if status == "CONFIRMED":
            text = (
                f"✅ *Booking Confirmed!*\n\n"
                f"📋 *Summary:* {summary}\n\n"
                f"*Full Transcript:*\n{transcript}"
            )

        elif status == "ALTERNATIVES_OFFERED":
            alt_text = (
                f"\n📌 *Alternatives:* {alternatives}"
                if alternatives and alternatives != "NONE"
                else ""
            )
            text = (
                f"⚠️ *Requested slot not available*\n\n"
                f"📋 *Summary:* {summary}{alt_text}\n\n"
                f"*Full Transcript:*\n{transcript}\n\n"
                "────────────────\n"
                "Reply with the *new time* to confirm, or /exit."
            )

        elif status == "REJECTED":
            text = (
                f"❌ *Booking Rejected*\n\n"
                f"📋 *Summary:* {summary}\n\n"
                f"*Full Transcript:*\n{transcript}\n\n"
                "────────────────\n"
                "Try a different business or time with /start."
            )

        else:
            text = (
                f"📞 *Call Completed*\n\n"
                f"📋 *Summary:* {summary}\n\n"
                f"*Full Transcript:*\n{transcript}\n\n"
                "────────────────\n"
                "Reply with *new time* or /exit."
            )

    if TELEGRAM_BOT_TOKEN:
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            requests.post(
                tg_url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown"
                },
                timeout=15
            )
        except Exception as e:
            print(f"Telegram send error: {str(e)}")

    if call_id in call_sessions:
        del call_sessions[call_id]

    return "OK", 200


# ============================================
# RUN SERVER
# ============================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
