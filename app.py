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

call_sessions = {}

# ============================================
# DEEPGRAM VOICE MODELS
# ============================================
DEEPGRAM_VOICES = {
    "english": "asteria",
    "hindi": "asteria",
    "tamil": "asteria",
    "telugu": "asteria",
    "kannada": "asteria",
    "malayalam": "asteria",
    "bengali": "asteria",
    "marathi": "asteria",
    "punjabi": "asteria",
    "gujarati": "asteria",
    "urdu": "asteria",
}

# ✅ DEFAULT VOICE FOR UNKNOWN LANGUAGES
DEFAULT_VOICE = "asteria"


def get_voice_by_language(language):
    """Get voice model, fallback to asteria for unknown languages"""
    language = language.lower().strip()
    return DEEPGRAM_VOICES.get(language, DEFAULT_VOICE)


def escape_markdown(text):
    """Escape special characters for Telegram Markdown."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', text)


def send_telegram_message(chat_id, text, parse_mode=None):
    """Send message to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print(f"WARN: Cannot send Telegram msg")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    if parse_mode:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }, timeout=10)

        if resp.status_code == 200:
            return True

    plain_text = text.replace("*", "").replace("`", "").replace("━", "-")
    resp = requests.post(url, json={
        "chat_id": chat_id,
        "text": plain_text
    }, timeout=10)

    return resp.status_code == 200


def extract_transcript_from_artifact(artifact):
    """Extract transcript from Vapi artifact."""
    if not artifact:
        return ""

    transcript = artifact.get("transcript", "")
    if transcript and transcript.strip():
        return transcript.strip()

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

    return ""


@app.route("/")
def home():
    return "Vapi + Deepgram (Multi-Language) ✅"


@app.route("/health")
def health():
    return "OK", 200


@app.route("/test-tts", methods=["POST"])
def test_tts():
    """Test Deepgram TTS"""
    data = request.json or {}
    text = data.get("text", "Hello")
    language = data.get("language", "english")

    voice_model = get_voice_by_language(language)

    return {
        "status": "✅ SUCCESS",
        "language": language,
        "voice_model": voice_model,
        "message": "Deepgram TTS configured for Vapi"
    }, 200


@app.route("/test-call", methods=["POST"])
def test_call():
    """Test call using Vapi with Deepgram voice"""
    data = request.json
    phone_number = data.get("phone") if data else None

    if not phone_number:
        return jsonify({"error": "Send {\"phone\": \"+91XXXXXXXXXX\"}"}), 400

    voice_model = get_voice_by_language("english")

    vapi_payload = {
        "assistant": {
            "firstMessage": "Hello! This is a test call.",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": "Quick test call. If person speaks another language, switch to it."
                    }
                ],
                "temperature": 0.3,
                "tools": [{"type": "dtmf"}],
            },
            "voice": {
                "provider": "deepgram",
                "voiceId": voice_model
            },
            "silenceTimeoutSeconds": 30,
            "maxDurationSeconds": 60
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {"number": phone_number}
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


def analyze_transcript(transcript):
    """Analyze call using Groq."""
    if not GROQ_API_KEY:
        return "UNKNOWN", "Could not analyze.", "", "english"

    prompt = f"""Analyze this transcript:

TRANSCRIPT:
{transcript}

Answer EXACTLY:
STATUS: <CONFIRMED / REJECTED / ALTERNATIVES_OFFERED / NO_CLEAR_OUTCOME>
SUMMARY: <1-2 sentences>
ALTERNATIVES: <slots or NONE>
DETECTED_LANGUAGE: <any language>
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

            status = "UNKNOWN"
            summary = ""
            alternatives = ""
            detected_lang = "english"

            for line in result.split("\n"):
                line = line.strip()
                if line.upper().startswith("STATUS:"):
                    status = line.split(":", 1)[1].strip().upper()
                elif line.upper().startswith("SUMMARY:"):
                    summary = line.split(":", 1)[1].strip()
                elif line.upper().startswith("ALTERNATIVES:"):
                    alternatives = line.split(":", 1)[1].strip()
                elif line.upper().startswith("DETECTED_LANGUAGE:"):
                    detected_lang = line.split(":", 1)[1].strip().lower()

            return status, summary, alternatives, detected_lang
        else:
            return "UNKNOWN", "Analysis failed.", "", "english"

    except Exception as e:
        print(f"Analysis exception: {str(e)}")
        return "UNKNOWN", "Analysis failed.", "", "english"


@app.route("/start-call", methods=["POST"])
def start_call():
    """Start a booking call"""
    data = request.json
    if not data:
        return jsonify({"error": "No data received"}), 400

    if not BASE_URL or not BASE_URL.startswith("https://"):
        return jsonify({"error": "BASE_URL not set correctly"}), 500

    phone_number = data.get("phone")
    chat_id = data.get("chat_id")
    business_name = data.get("business_name", "the business")
    goal = data.get("goal", "make an inquiry")
    details = data.get("details", {}) or {}
    customer_name = details.get("customer_name", "a customer")

    # ✅ ALWAYS START IN ENGLISH
    voice_model = get_voice_by_language("english")
    webhook_url = f"{BASE_URL}/vapi-webhook"

    is_confirmation = "confirm" in str(goal).lower()

    if is_confirmation:
        slot = details.get("slot_chosen", "the discussed time")
        opening_line = f"Hello, I am calling back for {customer_name}. We would like to confirm the slot for {slot}. Is that still available?"
        system_prompt = (
            f"Confirming booking for {customer_name} at {business_name}.\n"
            "LANGUAGE RULE: Start English, auto-detect customer's language, switch immediately.\n"
            "If slot unavailable, ask for 2-3 alternatives.\n"
        )
    else:
        opening_line = f"Hello, I'm calling for {customer_name} regarding a booking at {business_name}."
        system_prompt = (
            f"Calling for {customer_name} at {business_name}.\n"
            "LANGUAGE RULE: Start English, auto-detect customer's language, switch immediately.\n"
            "If slot taken, ask for alternatives.\n"
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
            "voice": {
                "provider": "deepgram",
                "voiceId": voice_model
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
        response = requests.post(
            "https://api.vapi.ai/call/phone",
            headers={
                "Authorization": f"Bearer {VAPI_API_KEY}",
                "Content-Type": "application/json"
            },
            json=vapi_payload,
            timeout=20
        )

        if response.status_code == 201:
            call_id = response.json().get("id")
            call_sessions[call_id] = {
                "chat_id": chat_id,
                "phone": phone_number,
                "business_name": business_name,
                "goal": goal,
                "details": details,
                "customer_name": customer_name,
            }
            return jsonify({"status": "calling", "call_id": call_id})
        else:
            return jsonify(response.json()), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    """Handle Vapi webhook events"""
    data = request.json
    if not data:
        return jsonify({}), 200

    event_type = data.get("type") or data.get("message", {}).get("type", "")

    if event_type in ["assistant-request", "status-update"]:
        return jsonify({}), 200

    if event_type == "end-of-call-report":
        msg = data if data.get("type") == "end-of-call-report" else data.get("message", data)

        call_id = (
            msg.get("call", {}).get("id")
            or msg.get("callId")
            or data.get("call", {}).get("id")
            or data.get("callId")
        )

        session = call_sessions.get(call_id)
        if not session:
            return jsonify({}), 200

        chat_id = session.get("chat_id")
        business_name = session.get("business_name", "the business")

        artifact = msg.get("artifact") or data.get("artifact") or {}
        transcript = extract_transcript_from_artifact(artifact)
        reason = msg.get("endedReason") or "unknown"

        if reason in ["customer-did-not-answer", "customer-busy", "voicemail", "no-answer"]:
            text = f"🚫 {business_name} not picking up.\nTry again later."
        elif not transcript:
            text = f"⚠️ Call connected but no recording.\nReason: {reason}"
        else:
            status, summary, alternatives, detected_lang = analyze_transcript(transcript)

            text = (
                f"📞 Call to {business_name} — Completed\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📌 Status: {status}\n"
                f"🌍 Language: {detected_lang.upper()}\n"
                f"📝 Summary: {summary}\n"
            )

            if status == "ALTERNATIVES_OFFERED" and alternatives != "NONE":
                text += f"\n⏳ Alternatives:\n{alternatives}"
            elif status == "CONFIRMED":
                text += "\n✅ Booking confirmed!"
            elif status == "REJECTED":
                text += "\n❌ Not accommodated."

            if len(transcript) > 2000:
                transcript = transcript[:2000] + "\n..."

            text += f"\n\n📜 Transcript:\n{transcript}"

        send_telegram_message(chat_id, text)

        if call_id in call_sessions:
            del call_sessions[call_id]

        return jsonify({}), 200

    return jsonify({}), 200


@app.route("/debug/sessions", methods=["GET"])
def debug_sessions():
    return jsonify({
        "active_sessions": len(call_sessions),
        "call_ids": list(call_sessions.keys())
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
