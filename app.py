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
# UTILITIES
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
    except Exception:
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
        return "UNKNOWN", "No Groq Key", ""
    prompt = f"""Analyze this phone call transcript between an AI booking assistant and a business:

{transcript}

The AI assistant was calling a business to book an appointment/reservation on behalf of a customer.

Answer EXACTLY in this format:
STATUS: <CONFIRMED / REJECTED / ALTERNATIVES_OFFERED / NO_CLEAR_OUTCOME>
SUMMARY: <1-2 sentences about what happened>
ALTERNATIVES: <List times/slots offered by business OR 'NONE'>
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
        status, summary, alternatives = "UNKNOWN", "", ""
        for line in res.split("\n"):
            upper = line.upper()
            if "STATUS:" in upper:
                status = line.split(":", 1)[1].strip()
            if "SUMMARY:" in upper:
                summary = line.split(":", 1)[1].strip()
            if "ALTERNATIVES:" in upper:
                alternatives = line.split(":", 1)[1].strip()
        return status, summary, alternatives
    except Exception:
        return "UNKNOWN", "Analysis failed", ""


# ============================================
# BUILD SYSTEM PROMPT (English Only)
# ============================================
def build_system_prompt(
    customer_name: str,
    business_name: str,
    slot_wanted: str,
    goal: str,
    details: dict,
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
You MUST speak ONLY in ENGLISH at all times. Every word you say must be in English.

If the person on the call speaks in ANY language other than English (Hindi, Bengali, Spanish, French, etc.):
1. First time: Say "I'm sorry, I can only communicate in English at the moment. Could we please continue in English?"
2. If they continue in another language: Say "I apologize, but I'm only able to speak in English right now. If you're not comfortable continuing in English, please feel free to end the call. Thank you for your time."
3. If they STILL continue in a non-English language after your second warning: End the call politely by saying "Thank you for your time. Goodbye." and stop speaking.

Do NOT attempt to speak, translate, or respond in any other language. English only.

=== CALL BEHAVIOR RULES ===
1. GREETING: When someone picks up, say your opening line. Assume the person is business staff.
2. HOLD/WAIT: If they say "wait", "hold on", "one moment", "one second", "let me check" — stay COMPLETELY SILENT. Do NOT speak until they speak again. Wait patiently.
3. PAUSE HANDLING: If there is silence on the other end for a few seconds, wait. Do NOT repeat yourself immediately. Give them at least 5-8 seconds before checking in with a gentle "Are you still there?"
4. IVR/DTMF: If you hear a machine saying "Press 1" or "Press 2", use the dtmf tool to press the digit. Do NOT speak the number.
5. SLOT UNAVAILABLE: If your requested time/date is not available:
   - Ask "What times do you have available?"
   - Get at least 2-3 alternative options
   - Do NOT hang up without getting alternatives
6. CONFIRMATION: Once the business confirms, repeat back the details to make sure everything is correct.
7. BE POLITE: Be professional and courteous throughout.
8. LISTEN FIRST: Always let the business person finish speaking before you respond.
9. STAY FOCUSED: Only discuss the booking. Do not go off-topic.
10. NO RUSHING: Speak at a calm, natural pace. Do not rush through your sentences.
"""

    return system_prompt


# ============================================
# BUILD OPENING LINE (English Only)
# ============================================
def build_opening_line(
    customer_name: str,
    business_name: str,
    slot_wanted: str,
    goal: str,
    details: dict,
    is_confirmation: bool,
) -> str:

    num_guests = details.get("num_guests", "")
    service_type = details.get("service_type", "")

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
# MAIN CALL ENDPOINT
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

    # Extract customer name
    customer_name = (
        details.get("customer_name")
        or details.get("guest_name")
        or details.get("patient_name")
        or "a customer"
    )

    # Extract slot
    slot_wanted = (
        details.get("slot_chosen")
        or details.get("time")
        or details.get("preferred_time")
        or details.get("date")
        or details.get("preferred_date")
        or "the requested time"
    )

    # Combine date + time if both exist
    date_val = details.get("date") or details.get("preferred_date") or ""
    time_val = details.get("time") or details.get("preferred_time") or ""
    if date_val and time_val and slot_wanted in [
        date_val,
        time_val,
        "the requested time",
    ]:
        slot_wanted = f"{date_val} at {time_val}"

    is_confirmation = "confirm" in str(goal).lower()

    # Build prompt and opening
    system_prompt = build_system_prompt(
        customer_name=customer_name,
        business_name=business_name,
        slot_wanted=slot_wanted,
        goal=goal,
        details=details,
        is_confirmation=is_confirmation,
    )

    opening_line = build_opening_line(
        customer_name=customer_name,
        business_name=business_name,
        slot_wanted=slot_wanted,
        goal=goal,
        details=details,
        is_confirmation=is_confirmation,
    )

    print(f"\n--- DEBUG [server.py] ---")
    print(f"Customer: {customer_name}")
    print(f"Business: {business_name}")
    print(f"Slot: {slot_wanted}")
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
            "voice": {
                "provider": "openai",
                "voiceId": "verse",
            },
            "transcriber": {
                "provider": "deepgram",
                "language": "en",
            },
            "serverUrl": f"{BASE_URL}/vapi-webhook",
            "silenceTimeoutSeconds": 45,
            "maxDurationSeconds": 600,
            "responseDelaySeconds": 0.5,
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
                status, summary, alternatives = analyze_transcript(transcript)

                customer = session.get("customer_name", "Customer")

                text = (
                    f"📞 <b>Call Result</b>\n\n"
                    f"🏢 Business: {session['business_name']}\n"
                    f"👤 Customer: {customer}\n"
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
