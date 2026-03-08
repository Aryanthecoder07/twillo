import os
import requests
from flask import Flask, request, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
from groq import Groq

app = Flask(__name__)

# ============================================
# CREDENTIALS & SETUP
# ============================================
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# NEW: We need your Telegram Token to send the receipt back!
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 

# YOUR RENDER URL (No trailing slash)
BASE_URL = os.environ.get("BASE_URL", "https://twillo-i353.onrender.com")

# The Human-Like Global Voice
VOICE_NAME = "Polly.Joanna-Neural"

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
groq_client = Groq(api_key=GROQ_API_KEY)

# In-memory storage for active calls
call_sessions = {}

# ============================================
# ROUTE 1: ROOT (Keep-Alive)
# ============================================
@app.route("/")
def home():
    return "AI Calling Backend Running ✅"

# ============================================
# ROUTE 2: START THE CALL (From Telegram)
# ============================================
@app.route("/start-call", methods=["POST"])
def start_call():
    data = request.json
    
    phone_number = data.get("phone")
    chat_id = data.get("chat_id") # <-- Capturing the Telegram chat ID!
    business_type = data.get("business_type", "Business")
    goal = data.get("goal", "make an inquiry")
    details = data.get("details", {})

    try:
        call = twilio_client.calls.create(
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{BASE_URL}/outbound-voice"
        )
        
        # Save all details, INCLUDING chat_id, to memory
        call_sessions[call.sid] = {
            "chat_id": chat_id,
            "business_type": business_type,
            "goal": goal,
            "details": details,
            "conversation": []
        }
        
        return jsonify({"status": "calling", "call_sid": call.sid})
    except Exception as e:
        print(f"Error starting call: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================
# ROUTE 3: TWILIO ANSWERS THE PHONE
# ============================================
@app.route("/outbound-voice", methods=["POST"])
def outbound_voice():
    call_sid = request.form.get("CallSid")
    session = call_sessions.get(call_sid)
    response = VoiceResponse()

    if not session:
        response.say("Sorry, an error occurred. Goodbye.", voice=VOICE_NAME)
        response.hangup()
        return str(response)

    # Construct the opening line
    customer_name = session["details"].get("customer_name", "a customer")
    opening_line = f"Hello, I am calling regarding {session['business_type'].lower()}. My name is {customer_name}."
    
    # Save bot's opening line to memory
    session["conversation"].append({"role": "assistant", "content": opening_line})
    
    # Speak the opening line with the Neural Voice
    gather = Gather(input="speech", action=f"/process-response?CallSid={call_sid}", speechTimeout="auto")
    gather.say(opening_line, voice=VOICE_NAME)
    response.append(gather)

    return str(response)

# ============================================
# ROUTE 4: AI PROCESSES USER SPEECH
# ============================================
@app.route("/process-response", methods=["POST"])
def process_response():
    call_sid = request.args.get("CallSid")
    user_speech = request.form.get("SpeechResult", "")
    
    session = call_sessions.get(call_sid)
    response = VoiceResponse()

    if not session or not user_speech:
        response.say("I didn't catch that. Could you repeat?", voice=VOICE_NAME)
        gather = Gather(input="speech", action=f"/process-response?CallSid={call_sid}", speechTimeout="auto")
        response.append(gather)
        return str(response)

    # Save user speech
    session["conversation"].append({"role": "user", "content": user_speech})

    # Build the strict Prompt for Groq
    system_prompt = f"""
    You are a polite AI assistant calling a {session['business_type']}.
    Your goal is: {session['goal']}.
    Here are the details you MUST provide if asked: {session['details']}.
    
    RULES:
    1. Keep responses very short (1-2 sentences max).
    2. Speak naturally like a human.
    3. If the goal is completely achieved or the business hangs up, your response MUST include the exact word [HANGUP].
    """

    try:
        # Ask Groq what to say (USING LLAMA-3.1-8B-INSTANT)
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "system", "content": system_prompt}] + session["conversation"]
        )
        ai_reply = completion.choices[0].message.content
        
        # We don't save [HANGUP] to the visual transcript
        clean_transcript_reply = ai_reply.replace("[HANGUP]", "").strip()
        session["conversation"].append({"role": "assistant", "content": clean_transcript_reply})

        # CHECK IF AI DECIDED TO HANG UP
        if "[HANGUP]" in ai_reply:
            response.say(clean_transcript_reply, voice=VOICE_NAME)
            response.hangup()
            
            # ==========================================
            # SEND FINAL TRANSCRIPT TO TELEGRAM
            # ==========================================
            chat_id = session.get("chat_id")
            if chat_id and TELEGRAM_BOT_TOKEN:
                
                # 1. Quick check if the booking was successful based on the chat
                full_chat = str(session["conversation"]).lower()
                if "confirm" in full_chat or "book" in full_chat or "thank" in full_chat:
                    header = "✅ **Booking Confirmed!**"
                else:
                    header = "❌ **Booking Failed or Cancelled.**"

                # 2. Start building the message
                summary = f"{header}\n\n**Call Transcript:**\n\n"
                
                # 3. Add the transcript
                for msg in session["conversation"]:
                    role = "🤖 AI" if msg["role"] == "assistant" else "👤 Business"
                    clean_msg = msg['content'].replace('[HANGUP]', '').strip()
                    if clean_msg:  # Only add if it's not empty
                        summary += f"{role}: {clean_msg}\n\n"
                
                # 4. Add the final instructions
                summary += "────────────────\n"
                summary += "🔄 **Send /start to make a new booking!**"

                # Send it!
                telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(telegram_url, json={"chat_id": chat_id, "text": summary})
            # ==========================================

        else:
            # Continue the conversation
            gather = Gather(input="speech", action=f"/process-response?CallSid={call_sid}", speechTimeout="auto")
            gather.say(ai_reply, voice=VOICE_NAME)
            response.append(gather)

    except Exception as e:
        print(f"🚨 GROQ API ERROR: {str(e)}", flush=True) 
        response.say("I'm experiencing technical difficulties. I will call back later.", voice=VOICE_NAME)
        response.hangup()

    return str(response)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
