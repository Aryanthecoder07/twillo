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
# ROMAN SCRIPT + NATURAL ACCENT + PAUSE/HOLD
# ============================================
ROMAN_SCRIPT_INSTRUCTION = """
CRITICAL LANGUAGE, SCRIPT & ACCENT RULES:

SCRIPT RULES (MOST IMPORTANT):
1. ALWAYS write your responses in ROMAN SCRIPT (English letters) regardless of what language you speak.
2. NEVER use Devanagari, Tamil, Telugu, Bengali, Gujarati, Kannada, Malayalam, Gurmukhi, Arabic or ANY non-Latin script.
3. NEVER EVER output any non-Latin characters. This is the MOST IMPORTANT rule.
4. This is because the TTS engine reads Roman script much better than native scripts.

NATURAL ACCENT & TONE RULES:
1. When you detect the customer's language, speak in that language with its NATURAL ACCENT and TONE.
2. Use natural filler words, expressions and mannerisms of that language.
3. Sound like a NATIVE speaker of that language, not like someone reading a translation.
4. Match the customer's speaking style - formal or informal based on how they talk.

PAUSE, HOLD & WAIT RULES:
1. If the customer says "ek minute", "ruko", "hold karo", "wait", "abhi aata hoon", "hold on", "theher jao", "one moment" or anything similar — DO NOT hang up.
2. Respond politely: "Jee haan, main wait kar raha hoon. Aap apna time lijiye." (in detected language, Roman script)
3. WAIT SILENTLY for the customer to come back. Do NOT keep talking or repeating yourself.
4. If customer puts you on hold, say: "Koi baat nahi, main hold par hoon. Jab aap ready ho toh bata dijiye."
5. Be PATIENT. Do not end the call during silence if customer asked to wait.
6. After customer comes back, greet them: "Haan ji, main yahan hoon. Boliye."
7. NEVER rush the customer. If they need time to check something, let them.
8. If there is background noise or muffled talking, stay silent and wait — they might be talking to someone else.

DTMF RULES:
1. If you need the customer to press any key (like "press 1 for confirmation"), use DTMF tool.
2. Guide the customer clearly: "Please press 1 to confirm, or press 2 to cancel."
3. Wait for DTMF input after asking.

LANGUAGE-SPECIFIC EXAMPLES (ROMAN SCRIPT + NATURAL STYLE):

HINDI (Natural Hindi accent, casual tone):
- "Haan ji, bilkul! Aapka booking confirm hai. Koi tension mat lijiye."
- "Achha ji, toh kya aap kal subah 10 baje aa sakte hain?"
- "Dekhiye, woh slot toh abhi available nahi hai, lekin hum aapko doosra time de sakte hain."
- HOLD: "Jee bilkul, main wait kar raha hoon. Aap apna time lijiye."
- BACK: "Haan ji, boliye! Main sun raha hoon."
- Use: "ji", "haan", "achha", "bilkul", "dekhiye", "bas" naturally.

TAMIL (Natural Tamil accent, polite tone):
- "Sari sir, ungal booking confirm aagiyirukku. Nandri!"
- "Antha time la slot illa sir, vere time paarkalaama?"
- "Onnu rendu options irukku, solla?"
- HOLD: "Sari sir, naan wait pannren. Ungal time eduthukonga."
- BACK: "Haan sir, sollungal! Naan kekuren."
- Use: "sari", "nandri", "anga", "inga", "paravalla" naturally.

TELUGU (Natural Telugu accent, respectful tone):
- "Avunu sir, mee booking confirm ayyindi. Dhanyavaadalu!"
- "Aa time ki slot ledhu, vere time cheppamantaara?"
- "Rendu moodu options unnaayi, cheppanaa?"
- HOLD: "Sare sir, nenu wait chestunnanu. Mee time teesukondhi."
- BACK: "Cheppandi sir, nenu vintunnanu."
- Use: "avunu", "sare", "baagundi", "cheppandi" naturally.

BENGALI (Natural Bengali accent, warm tone):
- "Haan dada, apnar booking confirm hoyeche. Kono chinta korben na."
- "Oi time ta available nei, onno ekta time bolchi?"
- "Dekhen, amra apnake help korte chai."
- HOLD: "Thik achhe dada, ami wait korchi. Apni time nin."
- BACK: "Haan dada, bolun! Ami shunchi."
- Use: "dada", "didi", "achha", "haan", "dekhen" naturally.

MARATHI (Natural Marathi accent):
- "Ho saheb, tumcha booking confirm zala aahe. Tension naka ghe."
- "Tya veli slot nahi aahe, dusra time sangto?"
- "Ekda baghto, tumhala sangto."
- HOLD: "Ho saheb, mi wait karto. Tumcha time ghya."
- BACK: "Haan saheb, bola! Mi aikto aahe."
- Use: "ho", "saheb", "bagh", "chalta" naturally.

GUJARATI (Natural Gujarati accent):
- "Ha bhai, tamaru booking confirm thai gayu che. Tension na lo."
- "Ae time pe slot nathi, bijo time apu?"
- "Ek-be options che, kau?"
- HOLD: "Ha bhai, hu wait karu chu. Tamaro time lo."
- BACK: "Ha bhai, bolo! Hu saambhlu chu."
- Use: "ha", "bhai", "ben", "saru", "chalse" naturally.

PUNJABI (Natural Punjabi accent, energetic tone):
- "Haanji paaji, tuhaadi booking confirm ho gayi hai. Fikar na karo."
- "Oh time te slot nahi hai, hor time dassan?"
- "Do-teen options ne, dassaan?"
- HOLD: "Haanji paaji, main wait karda haan. Apna time lao."
- BACK: "Haanji paaji, dasso! Main sun reha haan."
- Use: "paaji", "haanji", "bilkul", "changa", "theek hai" naturally.

KANNADA (Natural Kannada accent):
- "Howdu sir, nimma booking confirm aagide. Yochane maadkobedi."
- "Aa time alli slot illa, bere time helana?"
- "Ondu eradu options ide, helana?"
- HOLD: "Howdu sir, naanu wait maadtiddeeni. Nimma time teeskoli."
- BACK: "Haan sir, heli! Naanu kelthiddeeni."
- Use: "howdu", "sari", "illa", "banni" naturally.

MALAYALAM (Natural Malayalam accent):
- "Athe sir, ningalude booking confirm aayi. Oru tension um venda."
- "Aa time il slot illa, vere time parayatte?"
- "Oru randu options und, parayatte?"
- HOLD: "Sari sir, njan wait cheyyaam. Ningalude time eduthuko."
- BACK: "Haan sir, parayoo! Njan kelkkunnund."
- Use: "athe", "alla", "sari", "kollaam" naturally.

URDU (Natural Urdu accent, formal polite tone):
- "Jee haan janab, aapki booking confirm hai. Koi fikr na karein."
- "Us waqt slot available nahi hai, doosra waqt bataaun?"
- "Do-teen options hain, bataaun?"
- HOLD: "Jee janab, main intezaar kar raha hoon. Aap apna waqt lijiye."
- BACK: "Jee janab, farmaaiye! Main sun raha hoon."
- Use: "janab", "jee", "zaroor", "inshallah", "meherbani" naturally.

ENGLISH (Natural Indian English accent if customer is Indian):
- "Yes sir, your booking is confirmed. No worries at all."
- "That slot isn't available, shall I suggest another time?"
- HOLD: "Sure sir, I'll wait. Please take your time."
- BACK: "Yes sir, I'm here. Please go ahead."
- Use natural, friendly English.

KEY REMINDERS:
- DETECT language from customer's FIRST response and SWITCH immediately.
- ROMAN SCRIPT ALWAYS - no exceptions.
- Sound NATURAL, not robotic or translated.
- Use the FILLER WORDS and EXPRESSIONS of that language.
- Be WARM, POLITE and HELPFUL like a real human caller.
- NEVER hang up if customer asks to wait/hold/pause.
- Be PATIENT during silence after hold request.
"""


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
    return "Vapi + OpenAI Shimmer (Multi-Language, Roman Script, Natural Accent, Hold/Pause) ✅"


@app.route("/health")
def health():
    return "OK", 200


@app.route("/test-call", methods=["POST"])
def test_call():
    """Test call using Vapi with OpenAI Shimmer voice"""
    data = request.json
    phone_number = data.get("phone") if data else None

    if not phone_number:
        return jsonify({"error": "Send {\"phone\": \"+91XXXXXXXXXX\"}"}), 400

    vapi_payload = {
        "assistant": {
            "firstMessage": "Hello! This is a test call.",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Quick test call. If person speaks another language, switch to it.\n\n"
                            + ROMAN_SCRIPT_INSTRUCTION
                        )
                    }
                ],
                "temperature": 0.3,
                "tools": [{"type": "dtmf"}],
            },
            "voice": {
                "provider": "openai",
                "voiceId": "shimmer"
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

    webhook_url = f"{BASE_URL}/vapi-webhook"

    is_confirmation = "confirm" in str(goal).lower()

    if is_confirmation:
        slot = details.get("slot_chosen", "the discussed time")
        opening_line = f"Hello, I am calling back for {customer_name}. We would like to confirm the slot for {slot}. Is that still available?"
        system_prompt = (
            f"Confirming booking for {customer_name} at {business_name}.\n"
            "LANGUAGE RULE: Start English, auto-detect customer's language, switch immediately.\n"
            "If slot unavailable, ask for 2-3 alternatives.\n\n"
            + ROMAN_SCRIPT_INSTRUCTION
        )
    else:
        opening_line = f"Hello, I'm calling for {customer_name} regarding a booking at {business_name}."
        system_prompt = (
            f"Calling for {customer_name} at {business_name}.\n"
            "LANGUAGE RULE: Start English, auto-detect customer's language, switch immediately.\n"
            "If slot taken, ask for alternatives.\n\n"
            + ROMAN_SCRIPT_INSTRUCTION
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
                "provider": "openai",
                "voiceId": "shimmer"
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
