from flask import Flask, request, jsonify
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from openai import OpenAI
import os

app = Flask(__name__)

# ============================================
# ENV VARIABLES
# ============================================
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

groq_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

# In-memory storage
call_sessions = {}

# Your public URL
BASE_URL = "https://twillo-i353.onrender.com" # IMPORTANT: Update this to your active Railway or Render URL


# ============================================
# ROOT
# ============================================
@app.route("/")
def home():
    return "AI Calling Backend Running ✅"


# ============================================
# START CALL (Triggered by Telegram)
# ============================================
@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.json

    phone_number = data.get("phone")
    business_type = data.get("business_type")
    goal = data.get("goal")
    details = data.get("details", {})

    if not phone_number:
        return jsonify({"error": "Phone number missing"}), 400

    # ==========================================
    # THE QUICK FIX: Overwrite "OTHER"
    # ==========================================
    if goal and goal.upper() == "OTHER":
        goal = details.get("Specific Requirements", "an appointment")
    # ==========================================

    try:
        call = twilio_client.calls.create(
            url=f"{BASE_URL}/outbound-voice",
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
        )

        call_sessions[call.sid] = {
            "business_type": business_type,
            "goal": goal,
            "details": details,
            "conversation": []
        }

        return jsonify({"status": "calling", "call_sid": call.sid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================
# FIRST MESSAGE
# ============================================
@app.route("/outbound-voice", methods=["POST"])
def outbound_voice():
    call_sid = request.form.get("CallSid")
    session = call_sessions.get(call_sid)
    response = VoiceResponse()

    if not session:
        response.say("Sorry, an error occurred. Goodbye.")
        response.hangup()
        return str(response)

    # action_on_empty_result prevents the call from dropping if they are silent
    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/process-response",
        method="POST",
        speech_timeout="auto",
        action_on_empty_result=True 
    )

    first_message = (
        f"Hello. I am calling regarding {session['goal']}. "
        f"My name is {session['details'].get('customer_name', 'Customer')}."
    )

    session["conversation"].append({"role": "assistant", "content": first_message})
    
    gather.say(first_message)
    response.append(gather)

    return str(response)


# ============================================
# PROCESS RESPONSE
# ============================================
@app.route("/process-response", methods=["POST"])
def process_response():
    call_sid = request.form.get("CallSid")
    user_speech = request.form.get("SpeechResult")
    session = call_sessions.get(call_sid)
    response = VoiceResponse()

    if not session:
        response.say("Session expired. Goodbye.")
        response.hangup()
        return str(response)

    # 1. Handle Empty Speech (Silence or unrecognized audio)
    if not user_speech:
        gather = Gather(
            input="speech",
            action=f"{BASE_URL}/process-response",
            method="POST",
            speech_timeout="auto",
            action_on_empty_result=True
        )
        gather.say("I'm sorry, I didn't catch that. Are you still there?")
        response.append(gather)
        return str(response)

    session["conversation"].append({"role": "user", "content": user_speech})

    # 2. Strong Prompt Engineering for Call Termination
    system_prompt = f"""
You are an AI assistant making a professional booking call.
Business Type: {session['business_type']}
Goal: {session['goal']}
Details: {session['details']}

Rules:
- Speak professionally and keep replies to 1 or 2 short sentences.
- Confirm the booking clearly based on the details provided.
- IMPORTANT: When the booking is fully confirmed and the conversation is naturally ending, you MUST output the exact word [HANGUP] at the very end of your final sentence. Do not use this word until it is time to say goodbye.
"""

    try:
        completion = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "system", "content": system_prompt}] + session["conversation"]
        )
        ai_reply = completion.choices[0].message.content
    except Exception as e:
        response.say("I'm experiencing technical difficulties. I will call back later.")
        response.hangup()
        return str(response)

    session["conversation"].append({"role": "assistant", "content": ai_reply})

    # 3. Check for our secure Hangup Token
    if "[HANGUP]" in ai_reply:
        clean_reply = ai_reply.replace("[HANGUP]", "").strip()
        response.say(clean_reply)
        response.hangup()
    else:
        gather = Gather(
            input="speech",
            action=f"{BASE_URL}/process-response",
            method="POST",
            speech_timeout="auto",
            action_on_empty_result=True
        )
        gather.say(ai_reply)
        response.append(gather)

    return str(response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
