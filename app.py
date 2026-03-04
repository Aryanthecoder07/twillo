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

# Twilio Client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Groq Client (OpenAI compatible)
groq_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

# In-memory call sessions
call_sessions = {}


# ============================================
# ROOT TEST ROUTE
# ============================================
@app.route("/")
def home():
    return "AI Calling Backend Running ✅"


# ============================================
# START CALL (Telegram hits this)
# ============================================
@app.route("/start-call", methods=["POST"])
def start_call():

    data = request.json

    phone_number = data.get("phone")
    business_type = data.get("business_type")
    goal = data.get("goal")
    details = data.get("details")

    if not phone_number:
        return jsonify({"error": "Phone number missing"}), 400

    call = twilio_client.calls.create(
        url=f"{request.host_url}outbound-voice",
        to=phone_number,
        from_=TWILIO_PHONE_NUMBER,
    )

    call_sessions[call.sid] = {
        "business_type": business_type,
        "goal": goal,
        "details": details,
        "conversation": []
    }

    return jsonify({
        "status": "calling",
        "call_sid": call.sid
    })


# ============================================
# FIRST AI MESSAGE
# ============================================
@app.route("/outbound-voice", methods=["POST"])
def outbound_voice():

    call_sid = request.form.get("CallSid")
    session = call_sessions.get(call_sid)

    response = VoiceResponse()

    gather = Gather(
        input="speech",
        action="/process-response",
        method="POST",
        speech_timeout="auto"
    )

    first_message = (
        f"Hello, I am calling regarding {session['goal']}. "
        f"My name is {session['details'].get('customer_name', 'Customer')}."
    )

    session["conversation"].append({
        "role": "assistant",
        "content": first_message
    })

    gather.say(first_message)
    response.append(gather)

    return str(response)


# ============================================
# PROCESS RESPONSE (LIVE CONVERSATION)
# ============================================
@app.route("/process-response", methods=["POST"])
def process_response():

    call_sid = request.form.get("CallSid")
    user_speech = request.form.get("SpeechResult")

    session = call_sessions.get(call_sid)

    session["conversation"].append({
        "role": "user",
        "content": user_speech
    })

    completion = groq_client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[
            {
                "role": "system",
                "content": f"""
You are an AI assistant making a professional phone call.

Business Type: {session['business_type']}
Goal: {session['goal']}
Booking Details: {session['details']}

Rules:
- Speak clearly and professionally.
- Keep replies short (1-2 sentences).
- Confirm booking clearly.
- When booking confirmed, say confirmation and end call.
"""
            }
        ] + session["conversation"]
    )

    ai_reply = completion.choices[0].message.content

    session["conversation"].append({
        "role": "assistant",
        "content": ai_reply
    })

    response = VoiceResponse()

    if "confirmed" in ai_reply.lower():
        response.say(ai_reply)
        response.say("Thank you very much. Goodbye.")
        response.hangup()
    else:
        gather = Gather(
            input="speech",
            action="/process-response",
            method="POST",
            speech_timeout="auto"
        )
        gather.say(ai_reply)
        response.append(gather)

    return str(response)


# ============================================
# RUN APP
# ============================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
