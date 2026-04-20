import os
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
VAPI_API_KEY = os.environ.get("VAPI_API_KEY")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

# In-memory session store (consider Redis for production)
call_sessions = {}


def escape_markdown(text):
    """Escape special characters for Telegram Markdown."""
    # Escape characters that break Telegram Markdown parsing
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', text)


def send_telegram_message(chat_id, text, parse_mode=None):
    """
    Reliably send a Telegram message.
    Falls back to plain text if Markdown fails.
    """
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print(f"WARN: Cannot send Telegram msg. Token={bool(TELEGRAM_BOT_TOKEN)}, chat_id={chat_id}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # First attempt: with requested parse_mode
    if parse_mode:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }, timeout=10)

        if resp.status_code == 200:
            print(f"DEBUG: Telegram message sent (Markdown) to {chat_id}")
            return True
        else:
            print(f"WARN: Markdown send failed ({resp.status_code}): {resp.text}")

    # Fallback: plain text (strip markdown symbols)
    plain_text = text.replace("*", "").replace("`", "").replace("━", "-")
    resp = requests.post(url, json={
        "chat_id": chat_id,
        "text": plain_text
    }, timeout=10)

    if resp.status_code == 200:
        print(f"DEBUG: Telegram message sent (plain) to {chat_id}")
        return True
    else:
        print(f"ERROR: Telegram send failed entirely: {resp.status_code} {resp.text}")
        return False


def extract_transcript_from_artifact(artifact):
    """
    Extract transcript from Vapi artifact — handles both
    string transcript and messages array format.
    """
    if not artifact:
        return ""

    # Method 1: Direct transcript string
    transcript = artifact.get("transcript", "")
    if transcript and transcript.strip():
        return transcript.strip()

    # Method 2: Build from messages array
    messages = artifact.get("messages", [])
    if messages:
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content") or msg.get("message") or ""
            if content:
                label = "🤖 AI" if role == "assistant" else "👤 Business"
                lines.append(f"{label}: {content}")
        if lines:
            return "\n".join(lines)

    # Method 3: Check for recordingUrl or summary as last resort
    summary = artifact.get("summary", "")
    if summary:
        return f"[Summary only] {summary}"

    return ""


@app.route("/")
def home():
    return "Vapi Calling Backend: Online ✅"


@app.route("/health")
def health():
    return "OK", 200


# ============================================
# DIAGNOSTIC TEST CALL
# ============================================
@app.route("/test-call", methods=["POST"])
def test_call():
    data = request.json
    phone_number = data.get("phone") if data else None

    if not phone_number:
        return jsonify({"error": "Send {\"phone\": \"+91XXXXXXXXXX\"}"}), 400

    vapi_payload = {
        "assistant": {
            "firstMessage": "Hello! This is a test call. Can you hear me clearly?",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are making a quick test call. Greet the person. "
                            "Ask if they can hear you. Then say goodbye.\n\n"
                            "IVR RULES:\n"
                            "- If you hear an automated menu, navigate it.\n"
                            "- Choose English if available.\n"
                            "- Try to reach a human, then say goodbye.\n"
                        )
                    }
                ],
                "temperature": 0.3,
                "tools": [{"type": "dtmf"}],
            },
            "voice": {"provider": "openai", "voiceId": "verse"},
            "silenceTimeoutSeconds": 30,
            "maxDurationSeconds": 60
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {"number": phone_number}
    }

    try:
        print(f"DEBUG: Test Call to {phone_number}")
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
        print(f"TEST CALL Exception: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ============================================
# AI TRANSCRIPT ANALYZER (GROQ)
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
SUMMARY: <1-2 sentence summary of what happened>
ALTERNATIVES: <if alternative times/slots were offered, list them clearly. Otherwise write NONE>

Rules:
- If the business said yes/okay/available/confirmed → STATUS: CONFIRMED
- If they said no/not available but gave other options → STATUS: ALTERNATIVES_OFFERED  
- If they flatly refused → STATUS: REJECTED
- If unclear or cut off → STATUS: NO_CLEAR_OUTCOME
- Understand Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Punjabi, Gujarati, Urdu
- Even if garbled or mixed language, try your best
"""

    try:
        print("DEBUG: Sending transcript to Groq...")
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
            print(f"DEBUG GROQ ANALYSIS:\n{result}")

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
        print(f"ERROR: BASE_URL invalid: '{BASE_URL}'")
        return jsonify({"error": "BASE_URL env var not set correctly."}), 500

    phone_number = data.get("phone")
    chat_id = data.get("chat_id")
    business_name = data.get("business_name", "the business")
    goal = data.get("goal", "make an inquiry")
    details = data.get("details", {}) or {}
    customer_name = details.get("customer_name", "a customer")

    webhook_url = f"{BASE_URL}/vapi-webhook"
    print(f"DEBUG: webhook_url = {webhook_url}")

    is_confirmation = "confirm" in str(goal).lower()

    ivr_rules = """
IVR / DIALPAD RULES (VERY IMPORTANT):
- If you hear an automated menu, navigate it — don't talk over it.
- Choose English if available.
- Try to reach a human for bookings/reservations.
- Press 0 for operator if nothing else fits.
- WAIT for each prompt before pressing keys or speaking.
"""

    if is_confirmation:
        slot = details.get("slot_chosen", "the discussed time")
        opening_line = (
            f"Hello, I am calling back for {customer_name}. "
            f"We would like to confirm the slot for {slot}. Is that still available?"
        )
        system_prompt = (
            f"You are confirming a booking for {customer_name} at "
            f"{business_name} for {slot}.\n\n"
            "RULES:\n"
            "- Be brief and polite. Confirm availability clearly.\n"
            "- If the slot is NOT available, ask for 2-3 specific "
            "alternative times/dates. IMPORTANT: Get exact times.\n"
            "- Repeat each alternative back to confirm you heard correctly.\n"
            "- Say you will check with the customer and call back.\n"
            "- ALWAYS speak immediately when someone answers.\n"
            "- Match the language the other person speaks.\n"
            "- If put on hold, wait silently.\n"
            "- If silence > 20s, say 'Hello, are you there?' once.\n"
            "- Never hang up due to hold music or silence.\n"
            f"{ivr_rules}"
        )
    else:
        opening_line = (
            f"Hello, I'm calling for {customer_name} regarding "
            f"a booking at {business_name}. Am I speaking with the right place?"
        )
        system_prompt = (
            f"You are a polite phone assistant calling on behalf of "
            f"{customer_name}.\n"
            f"Calling: {business_name}\n"
            f"Goal: {goal}\n"
            f"Details: {details}\n\n"
            "RULES:\n"
            "- ALWAYS speak immediately when someone answers.\n"
            "- If the requested slot is taken, ask for 2-3 specific "
            "alternative times/dates. IMPORTANT: Get exact times.\n"
            "- Repeat each alternative back to confirm you heard correctly.\n"
            "- Once you have alternatives, say you will check with the "
            "customer and call back. Then end the call politely.\n"
            "- Match the language the other person speaks.\n"
            "- Use natural colloquial phrasing.\n"
            "- If put on hold, wait silently.\n"
            "- If silence > 20s, say 'Hello, are you there?' once.\n"
            "- Never hang up due to hold music or silence.\n"
            "- Be concise, natural, human-like.\n"
            f"{ivr_rules}"
        )

    vapi_payload = {
        "assistant": {
            "firstMessage": opening_line,
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt}
                ],
                "temperature": 0.3,
                "tools": [{"type": "dtmf"}]
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
        "customer": {"number": phone_number}
    }

    try:
        print(f"DEBUG: Starting call to {phone_number}")
        response = requests.post(
            "https://api.vapi.ai/call/phone",
            headers={
                "Authorization": f"Bearer {VAPI_API_KEY}",
                "Content-Type": "application/json"
            },
            json=vapi_payload,
            timeout=20
        )

        print(f"DEBUG: Vapi response: {response.status_code} {response.text}")

        if response.status_code == 201:
            call_id = response.json().get("id")
            call_sessions[call_id] = {
                "chat_id": chat_id,
                "phone": phone_number,
                "business_name": business_name,
                "goal": goal,
                "details": details,
                "customer_name": customer_name
            }
            print(f"DEBUG: Call started. call_id={call_id}, session stored.")
            return jsonify({"status": "calling", "call_id": call_id})
        else:
            return jsonify(response.json()), response.status_code

    except Exception as e:
        print(f"Exception in /start-call: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ============================================
# VAPI WEBHOOK — HANDLES ALL EVENTS
# ============================================
@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    data = request.json
    if not data:
        print("WARN: Empty webhook payload")
        return jsonify({}), 200

    # --- Log raw payload for debugging ---
    event_type = data.get("type") or data.get("message", {}).get("type", "")
    print(f"DEBUG WEBHOOK: event_type={event_type}")
    print(f"DEBUG WEBHOOK: keys={list(data.keys())}")

    # --- Handle assistant-request (Vapi expects config back) ---
    if event_type == "assistant-request":
        print("DEBUG: assistant-request received — returning empty (using payload config)")
        return jsonify({}), 200

    # --- Handle status-update ---
    if event_type == "status-update":
        status_data = data.get("message", data)
        status = status_data.get("status", "")
        call_id = status_data.get("call", {}).get("id", "")
        print(f"DEBUG: status-update: status={status}, call_id={call_id}")
        return jsonify({}), 200

    # --- Handle end-of-call-report ---
    if event_type == "end-of-call-report":
        # Vapi can nest under "message" or send at top level
        msg = data if data.get("type") == "end-of-call-report" else data.get("message", data)

        # Extract call_id (try multiple locations)
        call_id = (
            msg.get("call", {}).get("id")
            or msg.get("callId")
            or data.get("call", {}).get("id")
            or data.get("callId")
        )

        print(f"DEBUG: end-of-call-report call_id={call_id}")
        print(f"DEBUG: Known sessions: {list(call_sessions.keys())}")

        session = call_sessions.get(call_id)
        if not session:
            print(f"WARN: No session for call_id={call_id}. "
                  f"Payload call keys: {list(msg.get('call', {}).keys())}")
            return jsonify({}), 200

        chat_id = session.get("chat_id")
        business_name = session.get("business_name", "the business")
        customer_name = session.get("customer_name", "the customer")

        # --- Extract transcript (robust) ---
        artifact = msg.get("artifact") or data.get("artifact") or {}
        transcript = extract_transcript_from_artifact(artifact)

        reason = (
            msg.get("endedReason")
            or msg.get("call", {}).get("endedReason")
            or "unknown"
        )

        print(f"DEBUG: endedReason={reason}")
        print(f"DEBUG: transcript length={len(transcript)}")
        print(f"DEBUG: transcript preview={transcript[:200]}")

        # --- Build user message based on outcome ---
        if reason in [
            "customer-did-not-answer",
            "customer-busy",
            "voicemail",
            "no-answer"
        ]:
            text = (
                f"🚫 {business_name} is not picking up calls.\n"
                "Please try again later or try a different number."
            )
        elif not transcript:
            text = (
                f"⚠️ Call connected to {business_name} but "
                f"no conversation was recorded.\n"
                f"Reason: {reason}\n\n"
                "This can happen if the call dropped immediately "
                "or if there was only hold music."
            )
        else:
            # --- Analyze with AI ---
            status, summary, alternatives = analyze_transcript(transcript)

            text = (
                f"📞 Call to {business_name} — Completed\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📌 Status: {status}\n"
                f"📝 Summary: {summary}\n"
            )

            # --- KEY FIX: Handle alternatives properly ---
            if status == "ALTERNATIVES_OFFERED" and alternatives and alternatives != "NONE":
                text += (
                    f"\n⏳ Alternative slots offered:\n{alternatives}\n\n"
                    f"👉 Please reply with your preferred slot and "
                    f"I'll call back to confirm it."
                )
            elif status == "CONFIRMED":
                text += "\n✅ Your booking has been confirmed!"
            elif status == "REJECTED":
                text += (
                    "\n❌ The business could not accommodate the request. "
                    "Would you like to try a different time or place?"
                )

            # Truncate transcript if too long for Telegram (4096 char limit)
            max_transcript_len = 2000
            if len(transcript) > max_transcript_len:
                transcript_display = transcript[:max_transcript_len] + "\n... (truncated)"
            else:
                transcript_display = transcript

            text += f"\n\n📜 Full Transcript:\n{transcript_display}"

        # --- Send to Telegram (with fallback) ---
        send_telegram_message(chat_id, text, parse_mode=None)  # Plain text = safe

        # Cleanup session
        if call_id in call_sessions:
            del call_sessions[call_id]

        return jsonify({}), 200

    # --- Handle any other event type ---
    print(f"DEBUG: Unhandled webhook event: {event_type}")
    return jsonify({}), 200


# ============================================
# DEBUG: List active sessions
# ============================================
@app.route("/debug/sessions", methods=["GET"])
def debug_sessions():
    return jsonify({
        "active_sessions": len(call_sessions),
        "call_ids": list(call_sessions.keys())
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
