from flask import Flask, request, jsonify
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from openai import OpenAI
import os

app = Flask(__name__)

# Load environment variables
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Groq client (OpenAI compatible)
groq_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

# Temporary in-memory session storage
call_sessions = {}

# ✅ Start Outbound Call
@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.json

    phone_number = data["phone"]

    call = twilio_client.calls.create(
        url=f"{request.host_url}outbound-voice",
        to=phone_number,
        from_=TWILIO_PHONE_NUMBER
    )

    call_sessions[call.sid] = {
        "business_type": data["business_type"],
        "goal": data["goal"],
        "details": data["details"],
        "conversation": []
    }

    return jsonify({
        "status": "calling",
        "call_sid": call.sid
    })


# ✅ First AI Message
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

    first_message = f"""
Hello, I am calling regarding {session['goal']}.
My name is {session['details'].get('name', 'Customer')}.
"""

    session["conversation"].append({
        "role": "assistant",
        "content": first_message
    })

    gather.say(first_message)
    response.append(gather)

    return str(response)


# ✅ Process Business Response
@app.route("/process-response", methods=["POST"])
def process_response():
    call_sid = request.form.get("CallSid")
    user_speech = request.form.get("SpeechResult")

    session = call_sessions.get(call_sid)

    session["conversation"].append({
        "role": "user",
        "content": user_speech
    })

    # Generate AI reply using Groq
    completion = groq_client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[
            {
                "role": "system",
                "content": f"""
You are an AI assistant making a phone call.

Business Type: {session['business_type']}
Goal: {session['goal']}
Customer Details: {session['details']}

Rules:
- Speak naturally and professionally.
- Keep responses short (max 2 sentences).
- Achieve the goal.
- Once booking is confirmed, clearly say confirmation and end politely.
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

    # Simple completion detection
    if "confirmed" in ai_reply.lower() or "appointment scheduled" in ai_reply.lower():
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


# ✅ Run App
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
