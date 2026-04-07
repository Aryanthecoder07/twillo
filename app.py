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
    """
    Ultra-minimal call with NO serverUrl.
    If this works but /start-call doesn't → webhook is the problem.
    If this also doesn't work → Vapi account/phone config issue.
    """
    data = request.json
    phone_number = data.get("phone")

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
                        "content": "You are making a quick test call. Greet the person. Ask if they can hear you. Then say goodbye."
                    }
                ],
                "temperature": 0.3
            },
            "voice": {
                "provider": "vapi",
                "voiceId": "Layla"
            },
            "silenceTimeoutSeconds": 30,
            "maxDurationSeconds": 60
            # NOTE: No serverUrl here — completely standalone
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
        print(f"TEST CALL Status: {response.status_code}")
        print(f"TEST CALL Response: {response.text}")
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
            "- If you reach an IVR/automated system, try to connect to a human. Stay in English for IVR.\n"
            "- If put on hold, wait silently until a person speaks, then greet them.\n"
            "- If silence lasts 20 seconds, say 'Hello, are you there?' once, then wait.\n"
            "- Never hang up because of a pause, hold music, or silence.\n"
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
            "- If you reach an IVR/automated system, try to connect to a human. Stay in English for IVR.\n"
            "- If put on hold, wait silently until a person speaks, then greet them.\n"
            "- If silence lasts 20 seconds, say 'Hello, are you there?' once, then wait.\n"
            "- Never hang up because of a pause, hold music, or silence.\n"
            "- Be concise, natural, and human-like.\n"
        )

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
                "temperature": 0.3
            },
            "voice": {
                "provider": "vapi",
                "voiceId": "Layla"
            },
            "serverUrl": webhook_url,
            "silenceTimeoutSeconds": 60,
            "maxDurationSeconds": 600,
            "responseDelaySeconds": 0.5,
            "numWordsToInterruptAssistant": 5
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {
            "number": phone_number
        }
    }

    print(f"DEBUG: Sending Vapi payload: {vapi_payload}")

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
# VAPI WEBHOOK — HANDLES ALL EVENT TYPES
# ============================================
@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    data = request.json
    print(f"DEBUG WEBHOOK RAW: {data}")

    if not data:
        return jsonify({}), 200

    # ============================================
    # DETECT EVENT TYPE (Vapi sends it in different formats)
    # ============================================
    event_type = data.get("type") or data.get("message", {}).get("type", "")
    print(f"DEBUG WEBHOOK EVENT TYPE: {event_type}")

    # ============================================
    # HANDLE: assistant-request
    # Vapi asks "what assistant should I use?"
    # We DON'T use this — our assistant is inline.
    # But we must respond properly or it blocks.
    # ============================================
    if event_type == "assistant-request":
        print("DEBUG: assistant-request received — returning empty (inline assistant used)")
        return jsonify({}), 200

    # ============================================
    # HANDLE: function-call / tool-calls
    # If Vapi thinks a tool was called, respond empty
    # ============================================
    if event_type in ["function-call", "tool-calls"]:
        print(f"DEBUG: {event_type} received — returning empty result")
        return jsonify({"results": []}), 200

    # ============================================
    # HANDLE: status-update
    # Vapi sends call status changes
    # ============================================
    if event_type == "status-update":
        status = data.get("status") or data.get("message", {}).get("status", "")
        print(f"DEBUG: status-update → {status}")
        return jsonify({}), 200

    # ============================================
    # HANDLE: speech-update
    # ============================================
    if event_type == "speech-update":
        print("DEBUG: speech-update received")
        return jsonify({}), 200

    # ============================================
    # HANDLE: transcript
    # ============================================
    if event_type in ["transcript", "conversation-update"]:
        print(f"DEBUG: {event_type} received")
        return jsonify({}), 200

    # ============================================
    # HANDLE: hang
    # ============================================
    if event_type == "hang":
        print("DEBUG: hang event received")
        return jsonify({}), 200

    # ============================================
    # HANDLE: end-of-call-report — THE MAIN ONE
    # ============================================
    if event_type == "end-of-call-report":
        if data.get("type") == "end-of-call-report":
            msg = data
        else:
            msg = data.get("message", {})

        call_id = msg.get("call", {}).get("id")
        session = call_sessions.get(call_id)
        if not session:
            print(f"DEBUG: No session found for call_id={call_id}")
            return jsonify({}), 200

        chat_id = session["chat_id"]
        transcript = msg.get("artifact", {}).get("transcript", "").strip()
        reason = msg.get("endedReason", "")

        print(f"DEBUG WEBHOOK: endedReason={reason}, transcript_length={len(transcript)}")
        print(f"DEBUG WEBHOOK: transcript={transcript}")

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

        return jsonify({}), 200

    # ============================================
    # HANDLE: ANY OTHER EVENT — RESPOND WITH JSON
    # ============================================
    print(f"DEBUG: Unhandled webhook event type: {event_type}")
    return jsonify({}), 200


# ============================================
# RUN SERVER
# ============================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
