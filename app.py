import os
import re
import requests
from flask import Flask, request, jsonify
#from dotenv import load_dotenv
import io

#load_dotenv()

app = Flask(__name__)

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
VAPI_API_KEY = os.environ.get("VAPI_API_KEY")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")  # ✅ Direct use
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

call_sessions = {}

# ============================================
# ELEVENLABS VOICE IDs
# ============================================
ELEVENLABS_VOICES = {
    "english": "21m00Tcm4TlvDq8ikWAM",      # Rachel
    "hindi": "21m00Tcm4TlvDq8ikWAM",       # Rachel
    "tamil": "EXAVITQu4vr4xnSDxMaL",       # Bella
    "telugu": "EXAVITQu4vr4xnSDxMaL",      # Bella
    "kannada": "zcAOhNBS0xF24SdqwLo1",     # Antoni
    "malayalam": "zcAOhNBS0xF24SdqwLo1",   # Antoni
    "bengali": "MF3mGyEYCl7XYWbV7V5l",     # Erin
    "marathi": "MF3mGyEYCl7XYWbV7V5l",     # Erin
    "punjabi": "pNInz6obpgDQGcFmaJgB",     # Adam
    "gujarati": "yoZ06sMSTe6XfoAXiL7u",    # Sam
    "urdu": "21m00Tcm4TlvDq8ikWAM"         # Rachel
}


def escape_markdown(text):
    """Escape special characters for Telegram Markdown."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', text)


def send_telegram_message(chat_id, text, parse_mode=None):
    """Send message to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print(f"WARN: Cannot send Telegram msg. Token={bool(TELEGRAM_BOT_TOKEN)}, chat_id={chat_id}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    if parse_mode:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }, timeout=10)

        if resp.status_code == 200:
            print(f"DEBUG: Telegram message sent to {chat_id}")
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


# ============================================
# ELEVENLABS DIRECT TTS API ✅ SEEDHA
# ============================================
def elevenlabs_tts(text, voice_id="21m00Tcm4TlvDq8ikWAM", language="english"):
    """
    Directly call ElevenLabs API for Text-to-Speech
    Returns: audio file bytes
    """
    if not ELEVENLABS_API_KEY:
        print("❌ ERROR: ELEVENLABS_API_KEY not set in .env")
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,  # ✅ Direct API key
        "Content-Type": "application/json"
    }

    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    try:
        print(f"🎤 ElevenLabs TTS Call - Language: {language}, Text: {text[:30]}...")
        response = requests.post(url, headers=headers, json=payload, timeout=15)

        if response.status_code == 200:
            print(f"✅ ElevenLabs SUCCESS")
            return response.content  # Audio bytes (MP3)
        else:
            print(f"❌ ElevenLabs Error: {response.status_code}")
            print(f"Response: {response.text}")
            return None

    except Exception as e:
        print(f"❌ Exception: {str(e)}")
        return None


@app.route("/")
def home():
    return "Vapi + ElevenLabs Direct TTS: Online ✅"


@app.route("/health")
def health():
    return "OK", 200


# ============================================
# TEST: Convert Text to Speech ✅
# ============================================
@app.route("/test-tts", methods=["POST"])
def test_tts():
    """
    Test ElevenLabs TTS directly
    
    POST /test-tts
    {
      "text": "Namaste, yeh ek test hai",
      "language": "hindi"
    }
    """
    data = request.json or {}
    text = data.get("text", "Hello, this is a test")
    language = data.get("language", "english")

    if language not in ELEVENLABS_VOICES:
        return jsonify({"error": f"Language '{language}' not supported"}), 400

    voice_id = ELEVENLABS_VOICES[language]

    # ✅ Direct ElevenLabs call
    audio_bytes = elevenlabs_tts(text, voice_id, language)

    if not audio_bytes:
        return jsonify({"error": "Failed to generate audio"}), 500

    # Return audio file
    return {
        "status": "✅ SUCCESS",
        "message": f"Audio generated for '{language}'",
        "voice_id": voice_id,
        "text": text,
        "audio_size_kb": round(len(audio_bytes) / 1024, 2)
    }, 200


# ============================================
# TEST CALL (WITH ELEVENLABS)
# ============================================
@app.route("/test-call", methods=["POST"])
def test_call():
    """Test call using Vapi with ElevenLabs voice"""
    data = request.json
    phone_number = data.get("phone") if data else None

    if not phone_number:
        return jsonify({"error": "Send {\"phone\": \"+91XXXXXXXXXX\"}"}), 400

    voice_id = ELEVENLABS_VOICES["english"]

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
                            "You are making a quick test call.\n"
                            "If the person responds in another language, switch to it.\n"
                            "Greet, ask if they hear you, then say goodbye.\n"
                        )
                    }
                ],
                "temperature": 0.3,
                "tools": [{"type": "dtmf"}],
            },
            "voice": {
                "provider": "11labs",  # ✅ ElevenLabs
                "voiceId": voice_id
            },
            "silenceTimeoutSeconds": 30,
            "maxDurationSeconds": 60
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {"number": phone_number}
    }

    try:
        print(f"DEBUG: Test Call to {phone_number} with ElevenLabs")
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
DETECTED_LANGUAGE: <english/hindi/tamil/telugu/kannada/malayalam/bengali/marathi/punjabi/gujarati/urdu>
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
        return jsonify({"error": "BASE_URL env var not set correctly."}), 500

    phone_number = data.get("phone")
    chat_id = data.get("chat_id")
    business_name = data.get("business_name", "the business")
    goal = data.get("goal", "make an inquiry")
    details = data.get("details", {}) or {}
    customer_name = details.get("customer_name", "a customer")

    voice_id = ELEVENLABS_VOICES["english"]
    webhook_url = f"{BASE_URL}/vapi-webhook"

    is_confirmation = "confirm" in str(goal).lower()

    if is_confirmation:
        slot = details.get("slot_chosen", "the discussed time")
        opening_line = (
            f"Hello, I am calling back for {customer_name}. "
            f"We would like to confirm the slot for {slot}. Is that still available?"
        )
        system_prompt = (
            f"You are confirming a booking for {customer_name} at {business_name}.\n"
            "LANGUAGE RULE: Start in English, switch if customer uses another language.\n"
            "If slot unavailable, ask for 2-3 alternatives.\n"
        )
    else:
        opening_line = (
            f"Hello, I'm calling for {customer_name} regarding "
            f"a booking at {business_name}. Am I speaking with the right place?"
        )
        system_prompt = (
            f"You are calling on behalf of {customer_name} for {business_name}.\n"
            "LANGUAGE RULE: Start in English, switch if customer uses another language.\n"
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
                "provider": "11labs",  # ✅ ElevenLabs
                "voiceId": voice_id
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
            text = f"🚫 {business_name} is not picking up calls.\nPlease try again later."
        elif not transcript:
            text = f"⚠️ Call to {business_name} connected but no recording.\nReason: {reason}"
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
                text += "\n❌ Request not accommodated."

            if len(transcript) > 2000:
                transcript = transcript[:2000] + "\n... (truncated)"

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
