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
    if not TELEGRAM_BOT_TOKEN or not chat_id: return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode: payload["parse_mode"] = parse_mode
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except: return False

def extract_transcript_from_artifact(artifact):
    if not artifact: return ""
    transcript = artifact.get("transcript", "")
    if transcript and transcript.strip(): return transcript.strip()
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
    if not GROQ_API_KEY: return "UNKNOWN", "No Groq Key", "", "english"
    prompt = f"""Analyze this transcript:
{transcript}

Answer EXACTLY in this format:
STATUS: <CONFIRMED / REJECTED / ALTERNATIVES_OFFERED / NO_CLEAR_OUTCOME>
SUMMARY: <1-2 sentences>
ALTERNATIVES: <List times/slots offered by business OR 'NONE'>
DETECTED_LANGUAGE: <any language>
"""
    try:
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}], "temperature": 0}, timeout=15)
        res = resp.json()["choices"][0]["message"]["content"].strip()
        status, summary, alternatives, lang = "UNKNOWN", "", "", "english"
        for line in res.split("\n"):
            if "STATUS:" in line.upper(): status = line.split(":", 1)[1].strip()
            if "SUMMARY:" in line.upper(): summary = line.split(":", 1)[1].strip()
            if "ALTERNATIVES:" in line.upper(): alternatives = line.split(":", 1)[1].strip()
            if "DETECTED_LANGUAGE:" in line.upper(): lang = line.split(":", 1)[1].strip()
        return status, summary, alternatives, lang
    except: return "UNKNOWN", "Analysis failed", "", "english"

# ============================================
# MAIN CALL LOGIC (Confirmation + DTMF + Hold)
# ============================================

@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.json
    if not data or not BASE_URL: return jsonify({"error": "Missing data"}), 400

    phone_number = data.get("phone")
    chat_id = data.get("chat_id")
    business_name = data.get("business_name", "the business")
    goal = data.get("goal", "inquiry")
    details = data.get("details", {})
    customer_name = details.get("customer_name", "a customer")
    slot_wanted = details.get("slot_chosen", "the requested time")
    
    # 📝 Language Selection (Telegram Choice)
    user_pref_lang = data.get("language", "english").lower()
    is_confirmation = "confirm" in str(goal).lower()

    # --- DYNAMIC PROMPT & OPENING ---
    if user_pref_lang == "bengali":
        if is_confirmation:
            opening_line = f"Nomoshkar, ami {customer_name} er hoye abar call korchi. Amra ki {slot_wanted} e booking ta confirm korte pari?"
        else:
            opening_line = f"Nomoshkar, ami {customer_name} er hoye call korchi. Amra ki {slot_wanted} e booking korte pari?"
        lang_rule = "You MUST speak ONLY in BENGALI. Understand what the user asks before replying."
    else:
        if is_confirmation:
            opening_line = f"Hello, I am calling back for {customer_name} to confirm the booking for {slot_wanted}."
        else:
            opening_line = f"Hello, I'm calling for {customer_name} to check availability for {slot_wanted} at {business_name}."
        lang_rule = "You MUST speak ONLY in ENGLISH. Listen carefully and do not give generic answers."

    system_prompt = (
        f"Role: Professional Voice-Education Agent for {customer_name}.\n"
        f"CORE RULE: {lang_rule}\n"
        "1. HOLD/WAIT RULE: If the person says 'wait', 'hold on', or 'ek minute', you MUST stay silent. Do not interrupt the silence.\n"
        "2. IVR/DTMF RULE: If you hear a machine or 'Press 1', DO NOT speak the number. Use the 'dtmf' tool immediately to press the digit. Wait for a human.\n"
        f"3. SLOT FULL LOGIC: If the slot for {slot_wanted} is full, ask for 2-3 alternative times. Do not end the call without alternatives.\n"
        "4. HUMAN DETECTION: Do not explain the call to a robot. Wait for a human 'Hello' or greeting.\n"
        "5. UNDERSTAND FIRST: Listen to the business owner's full sentence before responding."
    )

    vapi_payload = {
        "assistant": {
            "firstMessage": opening_line,
            "model": {
                "provider": "openai", "model": "gpt-4o-mini",
                "messages": [{"role": "system", "content": system_prompt}],
                "temperature": 0.2, # Higher accuracy
                "tools": [{"type": "dtmf"}]
            },
            "voice": { "provider": "deepgram", "voiceId": "aura-asteria-en" },
            "serverUrl": f"{BASE_URL}/vapi-webhook",
            "silenceTimeoutSeconds": 45,
            "maxDurationSeconds": 600,
            "responseDelaySeconds": 0.4,
            "numWordsToInterruptAssistant": 3
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {"number": phone_number}
    }

    try:
        response = requests.post("https://api.vapi.ai/call/phone",
            headers={"Authorization": f"Bearer {VAPI_API_KEY}", "Content-Type": "application/json"},
            json=vapi_payload, timeout=20)
        if response.status_code == 201:
            call_id = response.json().get("id")
            call_sessions[call_id] = {"chat_id": chat_id, "business_name": business_name, "details": details}
            return jsonify({"status": "calling", "call_id": call_id})
        return jsonify(response.json()), response.status_code
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/vapi-webhook", methods=["POST"])
def vapi_webhook():
    data = request.json
    if not data: return jsonify({}), 200
    msg = data.get("message", data)
    if msg.get("type") == "end-of-call-report":
        call_id = msg.get("call", {}).get("id") or msg.get("callId")
        session = call_sessions.pop(call_id, None)
        if session:
            transcript = extract_transcript_from_artifact(msg.get("artifact", {}))
            if transcript:
                status, summary, alternatives, lang = analyze_transcript(transcript)
                text = (
                    f"📞 Call Result: {session['business_name']}\n"
                    f"📌 Status: {status}\n"
                    f"📝 Summary: {summary}\n"
                )
                if status == "ALTERNATIVES_OFFERED" and alternatives != "NONE":
                    text += f"⏳ Alternatives: {alternatives}\n(Reply with the slot to call back and confirm)"
                
                text += f"\n📜 Transcript:\n{transcript[:1000]}"
                send_telegram_message(session['chat_id'], text)
    return jsonify({}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
