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

    language_instruction = (
        "\n\nCRITICAL LANGUAGE RULES: "
        "1. Detect the language the other person speaks in their first real sentence. "
        "2. Immediately switch to that same language for all responses. "
        "3. If they speak Hindi, reply only in Hindi. Tamil → Tamil. Telugu → Telugu. "
        "4. If they mix languages, match that style naturally. "
        "5. Never keep speaking English if they switched to another language, unless you are interacting with an automated phone system or IVR. "
        "6. Use natural colloquial phrasing, not textbook translations."
    )

    call_behavior_instruction = (
        "\n\nCALL BEHAVIOR RULES: "
        "1. If the call is placed on hold, remain silent and wait patiently for the human to return. "
        "2. Do not hang up because of hold music, ringing, silence, or transfer announcements. "
        "3. If you reach an IVR, phone menu, automated system, or recorded voice, always try to connect to a human. "
        "4. Always choose any valid option for operator, representative, receptionist, front desk, staff, or human assistance. "
        "5. If the automated system asks for language preference, always choose English. "
        "6. While interacting with an IVR, automated system, voicemail tree, or calling program, continue in English. "
        "7. If multiple options are given, prioritize: human/operator/reception/front desk > appointments/reservations/bookings > all other options. "
        "8. Do not get stuck repeating long sentences to the IVR; use short clear responses like 'English', 'operator', 'representative', 'reception', or the valid keypad/menu option. "
        "9. Once a human answers, resume the normal conversation and switch to the human's language if they speak another language. "
        "10. If transferred, stay on the line and continue patiently until connected."
    )

    silence_and_hold_instruction = (
        "\n\nSILENCE AND HOLD HANDLING RULES: "
        "1. If there is silence, DO NOT hang up. Wait patiently. "
        "2. If silence lasts more than 15 seconds, say 'Hello? Are you still there?' ONCE. "
        "3. After that, wait silently for at least another 45 seconds before considering the call dropped. "
        "4. Hold music, background noise, ringing tones, or muffled sounds mean the call is still active — keep waiting and DO NOT speak. "
        "5. Never say goodbye or end the call just because of a pause or hold. "
        "6. If you hear 'please hold' or 'one moment' or 'wait' in ANY language, remain completely silent and wait indefinitely. "
        "7. If transferred to another person or department, wait patiently for the new person to speak first. "
        "8. Do NOT repeatedly ask 'are you there?' — ask only ONCE after 15 seconds of true silence (no music, no noise). "
        "9. If hold music is playing, do NOT speak at all — just wait silently until a human voice returns. "
        "10. Consider the call dropped ONLY if there is absolute dead silence (no sound at all) for more than 60 seconds."
    )

    dtmf_instruction = (
        "\n\nDTMF / KEYPAD RULES (CRITICAL): "
        "1. When interacting with an IVR, phone menu, or automated system that asks you to 'press 1', 'press 2', etc., "
        "you MUST use the dtmf function to send the keypad tone. NEVER say the number out loud. "
        "2. To press a key, use the dtmf function with the appropriate digit (0-9, *, #). "
        "3. Examples: "
        "   - 'Press 1 for English' → use dtmf to send '1' "
        "   - 'Press 0 for operator' → use dtmf to send '0' "
        "   - 'Press 9 to repeat' → use dtmf to send '9' "
        "   - 'Press # to confirm' → use dtmf to send '#' "
        "   - 'Press * to go back' → use dtmf to send '*' "
        "4. If the menu says 'press or say', ALWAYS use dtmf to press — never speak the number. "
        "5. After pressing a key, wait silently for the system to respond. "
        "6. If you need to enter multiple digits (like an extension), send each digit using dtmf. "
        "7. Only use dtmf for IVR/automated systems. When talking to a real human, speak normally."
    )

    if is_confirmation:
        slot = details.get("slot_chosen", "the discussed time")
        opening_line = (
            f"Hello, I am calling back for {customer_name}. "
            f"We would like to confirm the slot for {slot}. Is that still available?"
        )
        system_prompt = (
            f"You are confirming a booking for {customer_name} at {business_name} for {slot}. "
            "Keep it brief and polite. Confirm availability clearly. "
            "If the slot is not available, ask for 2-3 alternative available times and say you will check with the customer and call back."
            + language_instruction
            + call_behavior_instruction
            + silence_and_hold_instruction
            + dtmf_instruction
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
            + call_behavior_instruction
            + silence_and_hold_instruction
            + dtmf_instruction
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
                "temperature": 0.3,
                "tools": [
                    {
                        "type": "dtmf"
                    }
                ]
            },
            "voice": {
                "provider": "openai",
                "voiceId": "shimmer"
            },
            "serverUrl": webhook_url,

            # ===== PREVENT EARLY HANGUP — SILENCE & HOLD PROTECTION =====
            "silenceTimeoutSeconds": 120,
            "maxDurationSeconds": 600,
            "responseDelaySeconds": 1.5,
            "numWordsToInterruptAssistant": 2,
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
            alt_text = f"\n📌 *Alternatives:* {alternatives}" if alternatives and alternatives != "NONE" else ""
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
