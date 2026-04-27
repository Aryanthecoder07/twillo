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
# UTILITIES & FORMATTING
# ============================================

def send_telegram_message(chat_id, text, parse_mode=None):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except:
        return False


def extract_transcript_from_artifact(artifact):
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
        return "\n".join(lines)
    return ""


def analyze_transcript(transcript):
    if not GROQ_API_KEY:
        return "UNKNOWN", "No Groq Key", "", "english"
    prompt = f"""Analyze this phone call transcript between an AI booking assistant and a business:

{transcript}

The AI assistant was calling a business to book an appointment/reservation on behalf of a customer.

Answer EXACTLY in this format:
STATUS: <CONFIRMED / REJECTED / ALTERNATIVES_OFFERED / NO_CLEAR_OUTCOME>
SUMMARY: <1-2 sentences about what happened>
ALTERNATIVES: <List times/slots offered by business OR 'NONE'>
DETECTED_LANGUAGE: <language used in the call>
"""
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=15,
        )
        res = resp.json()["choices"][0]["message"]["content"].strip()
        status, summary, alternatives, lang = "UNKNOWN", "", "", "english"
        for line in res.split("\n"):
            if "STATUS:" in line.upper():
                status = line.split(":", 1)[1].strip()
            if "SUMMARY:" in line.upper():
                summary = line.split(":", 1)[1].strip()
            if "ALTERNATIVES:" in line.upper():
                alternatives = line.split(":", 1)[1].strip()
            if "DETECTED_LANGUAGE:" in line.upper():
                lang = line.split(":", 1)[1].strip()
        return status, summary, alternatives, lang
    except:
        return "UNKNOWN", "Analysis failed", "", "english"


# ============================================
# ✅ VOICE CONFIG — Using shimmer (OpenAI)
# ============================================
def get_voice_config(language: str) -> dict:
    """
    Uses OpenAI 'shimmer' voice for ALL languages.
    shimmer supports multilingual output natively.
    """
    return {
        "provider": "openai",
        "voiceId": "shimmer",
    }


# ============================================
# ✅ FIXED: BUILD SYSTEM PROMPT
# ============================================
def build_system_prompt(
    customer_name: str,
    business_name: str,
    slot_wanted: str,
    goal: str,
    details: dict,
    language: str,
    is_confirmation: bool,
) -> str:

    # Build details string
    detail_lines = []
    skip_keys = ["business_name", "slot_chosen"]
    for k, v in details.items():
        if k in skip_keys:
            continue
        if v and str(v).strip().lower() not in [
            "",
            "none",
            "null",
            "not provided",
        ]:
            detail_lines.append(f"  - {k.replace('_', ' ').title()}: {v}")
    details_text = (
        "\n".join(detail_lines) if detail_lines else "  No extra details."
    )

    # Language rule
    if language == "bengali":
        lang_rule = (
            "You MUST speak ONLY in BENGALI (Bangla). "
            "Every single word must be in Bengali. "
            "Do NOT use English at all. "
            "Even if the business person speaks English, you reply in Bengali only."
        )
    else:
        lang_rule = (
            "You MUST speak ONLY in ENGLISH. "
            "Listen carefully and respond naturally."
        )

    # Task description
    if is_confirmation:
        task = (
            f"You are calling {business_name} to CONFIRM a booking that was "
            f"previously discussed.\n"
            f"Customer: {customer_name}\n"
            f"Slot to confirm: {slot_wanted}\n"
            f"Politely ask the business to confirm this booking."
        )
    else:
        task = (
            f"You are calling {business_name} to make a NEW booking/appointment.\n"
            f"Customer: {customer_name}\n"
            f"Requested slot: {slot_wanted}\n"
            f"Goal: {goal}\n\n"
            f"Booking Details:\n{details_text}"
        )

    system_prompt = f"""=== WHO YOU ARE ===
You are an AI phone assistant working for {customer_name}.
{customer_name} is your boss/client.
You are making a phone call TO {business_name} to book something for {customer_name}.

=== CRITICAL IDENTITY RULES ===
✅ You are CALLING the business. The person who picks up the phone works at {business_name}.
✅ Say: "I'm calling to make a booking for {customer_name}" or "I'd like to book on behalf of {customer_name}"
✅ The person answering the phone is the BUSINESS STAFF. Treat them as the business.

❌ NEVER say "I am calling from {business_name}" — you are NOT from the business.
❌ NEVER say "Am I talking to {customer_name}?" — {customer_name} is YOUR client, not the person on the phone.
❌ NEVER introduce yourself as {business_name} staff.
❌ NEVER ask the business person for THEIR name unless needed for the booking.

=== YOUR TASK ===
{task}

=== LANGUAGE RULE ===
{lang_rule}

=== CALL BEHAVIOR RULES ===
1. GREETING: When someone picks up, say your opening line. Assume the person is business staff.
2. HOLD/WAIT: If they say "wait", "hold on", "ek minute", "aektu darun" — stay COMPLETELY SILENT until they speak again.
3. IVR/DTMF: If you hear a machine saying "Press 1" or "Press 2", use the dtmf tool to press the digit. Do NOT speak the number.
4. SLOT UNAVAILABLE: If your requested time/date is not available:
   - Ask "What times do you have available?"
   - Get at least 2-3 alternative options
   - Do NOT hang up without getting alternatives
5. CONFIRMATION: Once the business confirms, repeat back the details to make sure everything is correct.
6. BE POLITE: Be professional and courteous throughout.
7. LISTEN FIRST: Always let the business person finish speaking before you respond.
8. STAY FOCUSED: Only discuss the booking. Do not go off-topic.
"""

    return system_prompt


# ============================================
# ✅ FIXED: BUILD OPENING LINE
# ============================================
def build_opening_line(
    customer_name: str,
    business_name: str,
    slot_wanted: str,
    goal: str,
    details: dict,
    language: str,
    is_confirmation: bool,
) -> str:

    num_guests = details.get("num_guests", "")
    service_type = details.get("service_type", "")

    if language == "bengali":
        if is_confirmation:
            return (
                f"Nomoshkar, ami {customer_name} er hoye call korchi. "
                f"Amra age {slot_wanted} er jonno ekta booking niye kotha bolechhilam. "
                f"Ami seta confirm korte chacchhi. Eta ki possible?"
            )
        else:
            extra = ""
            if num_guests:
                extra = f" {num_guests} jon er jonno"
            return (
                f"Nomoshkar, ami {customer_name} er hoye call korchi. "
                f"Ami {business_name} te{extra} {slot_wanted} er jonno ekta booking korte chacchhi. "
                f"Ei somoy ta ki available ache?"
            )
    else:
        if is_confirmation:
            return (
                f"Hi, I'm calling on behalf of {customer_name}. "
                f"We spoke earlier about a booking for {slot_wanted}. "
                f"I'd like to confirm that, please."
            )
        else:
            extra = ""
            if num_guests:
                extra = f" for {num_guests} people"
            if service_type:
                extra = f" for a {service_type}"
            return (
                f"Hi, I'm calling on behalf of {customer_name}. "
                f"I'd like to make a booking at {business_name}{extra} "
                f"for {slot_wanted}. Is that available?"
            )


# ============================================
# MAIN CALL ENDPOINT (✅ FULLY FIXED)
# ============================================

@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.json
    if not data or not BASE_URL:
        return jsonify({"error": "Missing data"}), 400

    phone_number = data.get("phone")
    chat_id = data.get("chat_id")
    business_name = data.get("business_name", "the business")
    goal = data.get("goal", "inquiry")
    details = data.get("details", {})

    # ✅ Extract customer name from multiple possible fields
    customer_name = (
        details.get("customer_name")
        or details.get("guest_name")
        or details.get("patient_name")
        or "a customer"
    )

    # ✅ Extract slot from multiple possible fields
    slot_wanted = (
        details.get("slot_chosen")
        or details.get("time")
        or details.get("preferred_time")
        or details.get("date")
        or details.get("preferred_date")
        or "the requested time"
    )

    # ✅ Combine date + time if both exist
    date_val = details.get("date") or details.get("preferred_date") or ""
    time_val = details.get("time") or details.get("preferred_time") or ""
    if date_val and time_val and slot_wanted in [
        date_val,
        time_val,
        "the requested time",
    ]:
        slot_wanted = f"{date_val} at {time_val}"

    # ✅ Get language
    user_pref_lang = data.get("language", "english").lower().strip()
    is_confirmation = "confirm" in str(goal).lower()

    # ✅ Build prompt and opening
    system_prompt = build_system_prompt(
        customer_name=customer_name,
        business_name=business_name,
        slot_wanted=slot_wanted,
        goal=goal,
        details=details,
        language=user_pref_lang,
        is_confirmation=is_confirmation,
    )

    opening_line = build_opening_line(
        customer_name=customer_name,
        business_name=business_name,
        slot_wanted=slot_wanted,
        goal=goal,
        details=details,
        language=user_pref_lang,
        is_confirmation=is_confirmation,
    )

    # ✅ shimmer voice for all languages
    voice_config = get_voice_config(user_pref_lang)

    # ✅ Language-aware transcriber
    if user_pref_lang == "bengali":
        transcriber_config = {
            "provider": "deepgram",
            "language": "bn",
        }
    else:
        transcriber_config = {
            "provider": "deepgram",
            "language": "en",
        }

    print(f"\n--- DEBUG [server.py] ---")
    print(f"Language: {user_pref_lang}")
    print(f"Customer: {customer_name}")
    print(f"Business: {business_name}")
    print(f"Slot: {slot_wanted}")
    print(f"Voice: {voice_config}")
    print(f"Opening: {opening_line}")
    print(f"Goal: {goal}")
    print(f"Details: {details}")
    print(f"-------------------------\n")

    vapi_payload = {
        "assistant": {
            "firstMessage": opening_line,
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt}
                ],
                "temperature": 0.2,
                "tools": [{"type": "dtmf"}],
            },
            "voice": voice_config,
            "transcriber": transcriber_config,
            "serverUrl": f"{BASE_URL}/vapi-webhook",
            "silenceTimeoutSeconds": 45,
            "maxDurationSeconds": 600,
            "responseDelaySeconds": 0.4,
            "numWordsToInterruptAssistant": 3,
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {"number": phone_number},
    }

    try:
        response = requests.post(
            "https://api.vapi.ai/call/phone",
            headers={
                "Authorization": f"Bearer {VAPI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=vapi_payload,
            timeout=20,
        )
        if response.status_code == 201:
            call_id = response.json().get("id")
            call_sessions[call_id] = {
                "chat_id": chat_id,
                "business_name": business_name,
                "customer_name": customer_name,
                "details": details,
                "language": user_pref_lang,
            }
            return jsonify({"status": "calling", "call_id": call_id})

        print(f"VAPI Error: {response.status_code} - {response.text}")
        return jsonify(response.json()), response.status_code
    except Exception as e:
        print(f"start_call exception: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================
# WEBHOOK
# ============================================

@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    data = request.json
    if not data:
        return jsonify({}), 200

    msg = data.get("message", data)

    if msg.get("type") == "end-of-call-report":
        call_id = msg.get("call", {}).get("id") or msg.get("callId")
        session = call_sessions.pop(call_id, None)

        if session:
            transcript = extract_transcript_from_artifact(
                msg.get("artifact", {})
            )
            if transcript:
                status, summary, alternatives, lang = analyze_transcript(
                    transcript
                )

                call_lang = session.get("language", "english")
                customer = session.get("customer_name", "Customer")

                text = (
                    f"📞 <b>Call Result</b>\n\n"
                    f"🏢 Business: {session['business_name']}\n"
                    f"👤 Customer: {customer}\n"
                    f"🌐 Language: {call_lang.capitalize()}\n"
                    f"📌 Status: {status}\n"
                    f"📝 Summary: {summary}\n"
                )

                if (
                    status == "ALTERNATIVES_OFFERED"
                    and alternatives
                    and alternatives.upper() != "NONE"
                ):
                    text += (
                        f"\n⏳ <b>Alternatives Offered:</b> {alternatives}\n"
                        f"💡 Reply with your preferred slot to call back and confirm."
                    )

                text += f"\n\n📜 <b>Transcript:</b>\n{transcript[:1000]}"
                send_telegram_message(
                    session["chat_id"], text, parse_mode="HTML"
                )

    return jsonify({}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
