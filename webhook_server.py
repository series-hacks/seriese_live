"""
Simplified Series Webhook Server

Handles:
- /conference/create - Creates conference with inline TwiML
- /recording-ready - Receives recording URL when conference ends
- /summary - Transcribes and summarizes recordings
- /audio/<filename> - Serves static audio files
- /health - Health check
"""
import os
import time
import logging
import tempfile
import requests
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient
from openai import OpenAI

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)

# Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
NGROK_URL = os.getenv('NGROK_URL')
WEBHOOK_PORT = int(os.getenv('WEBHOOK_PORT', 5002))
SERIES_API_KEY = os.getenv('SERIES_API_KEY')
SERIES_BASE_URL = os.getenv('SERIES_BASE_URL')

# Initialize clients
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Storage
conferences = {}  # conference_name -> {profiles, phones, created_at}
recording_urls = {}  # conference_name -> recording_url


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'conferences': len(conferences),
        'recordings': len(recording_urls),
        'ngrok_url': NGROK_URL
    })


@app.route('/audio/<filename>', methods=['GET'])
def serve_audio(filename):
    """Serve static audio files."""
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    return send_from_directory(static_dir, filename)


@app.route('/conference/create', methods=['POST'])
def create_conference():
    """
    Create a conference call between two participants.

    Expected JSON body:
    {
        "profile1": {"name": "...", "phone": "...", ...},
        "profile2": {"name": "...", "phone": "...", ...}
    }
    """
    data = request.get_json()

    profile1 = data.get('profile1', {})
    profile2 = data.get('profile2', {})

    phone1 = profile1.get('phone')
    phone2 = profile2.get('phone')

    if not phone1 or not phone2:
        return jsonify({'error': 'Both profiles must have phone numbers'}), 400

    # Create unique conference name
    conference_name = f"series-match-{int(time.time())}"

    # Store conference info
    conferences[conference_name] = {
        'profiles': [profile1, profile2],
        'phones': [phone1, phone2],
        'created_at': time.time()
    }

    # Build TwiML with inline audio and conference
    # Note: conference_name only has alphanums and dashes, no encoding needed
    audio_url = f"{NGROK_URL}/audio/intro.wav"
    recording_callback = f"{NGROK_URL}/recording-ready?conference={conference_name}"

    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Dial>
        <Conference record="record-from-start"
                    recordingStatusCallback="{recording_callback}"
                    recordingStatusCallbackEvent="completed">
            {conference_name}
        </Conference>
    </Dial>
</Response>'''

    logger.info(f"Creating conference {conference_name}")
    logger.info(f"TwiML: {twiml}")

    # Call both participants
    call_sids = []
    for phone in [phone1, phone2]:
        try:
            call = twilio_client.calls.create(
                to=phone,
                from_=TWILIO_PHONE_NUMBER,
                twiml=twiml
            )
            call_sids.append(call.sid)
            logger.info(f"Called {phone}: {call.sid}")
        except Exception as e:
            logger.error(f"Failed to call {phone}: {e}")

    return jsonify({
        'conference_name': conference_name,
        'call_sids': call_sids,
        'status': 'created'
    })


@app.route('/recording-ready', methods=['POST'])
def recording_ready():
    """
    Callback from Twilio when conference recording is ready.
    """
    conference_name = request.args.get('conference')
    recording_url = request.form.get('RecordingUrl')
    recording_sid = request.form.get('RecordingSid')

    logger.info(f"Recording ready for {conference_name}: {recording_url}")

    if conference_name and recording_url:
        recording_urls[conference_name] = {
            'url': recording_url,
            'sid': recording_sid,
            'timestamp': time.time()
        }

    return '', 200


@app.route('/summary', methods=['POST', 'GET'])
def summary():
    """
    Transcribe and summarize the most recent conference recording.
    Sends summary via iMessage.
    """
    logger.info("Summary request received")

    # Find the most recent recording
    if not recording_urls:
        logger.info("No recordings available")
        return jsonify({'error': 'No recordings available', 'recordings': 0}), 404

    # Get most recent recording
    most_recent = max(recording_urls.items(), key=lambda x: x[1]['timestamp'])
    conference_name, recording_info = most_recent

    logger.info(f"Processing recording for {conference_name}")

    # Get conference profiles
    conf_data = conferences.get(conference_name, {})
    profiles = conf_data.get('profiles', [{}, {}])
    phones = conf_data.get('phones', [])

    name1 = profiles[0].get('name', 'Participant 1') if profiles else 'Participant 1'
    name2 = profiles[1].get('name', 'Participant 2') if len(profiles) > 1 else 'Participant 2'

    # Download recording
    recording_url = recording_info['url']
    logger.info(f"Downloading recording from {recording_url}")

    try:
        # Twilio recordings need auth and .wav extension
        response = requests.get(
            f"{recording_url}.wav",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=60
        )

        if not response.ok:
            logger.error(f"Failed to download recording: {response.status_code}")
            return jsonify({'error': f'Failed to download recording: {response.status_code}'}), 500

        audio_bytes = response.content
        logger.info(f"Downloaded {len(audio_bytes)} bytes")

    except Exception as e:
        logger.error(f"Error downloading recording: {e}")
        return jsonify({'error': str(e)}), 500

    # Transcribe with Whisper
    logger.info("Transcribing with Whisper...")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name

        with open(temp_path, 'rb') as audio_file:
            transcription = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )

        logger.info(f"Transcription: {transcription[:200]}...")

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return jsonify({'error': f'Transcription failed: {e}'}), 500
    finally:
        # Always clean up temp file
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

    # Summarize with GPT
    logger.info("Generating summary...")
    try:
        prompt = f"""You are a meeting notetaker. Summarize this conversation between {name1} and {name2}.

Create a concise summary that includes:
1. Key topics discussed
2. Any action items or follow-ups mentioned
3. Interesting shared interests discovered
4. Potential collaboration opportunities

Keep it brief and professional (under 200 words).
IMPORTANT: Use only plain ASCII characters. Avoid smart quotes, em-dashes, and other special Unicode characters.

Conversation transcript:
{transcription}

Summary:"""

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful meeting notetaker. Be concise and highlight key points."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.5
        )

        summary_text = response.choices[0].message.content.strip()
        logger.info(f"Summary: {summary_text}")

    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        return jsonify({'error': f'Summary generation failed: {e}'}), 500

    # Send summary via iMessage to participants
    full_message = f"Summary of your call:\n\n{summary_text}"

    for phone in phones:
        if phone:
            try:
                send_imessage(phone, full_message)
                logger.info(f"Sent summary to {phone}")
            except Exception as e:
                logger.error(f"Failed to send to {phone}: {e}")

    return jsonify({
        'conference': conference_name,
        'participants': [name1, name2],
        'transcript_length': len(transcription),
        'summary': summary_text,
        'sent_to': phones
    })


def send_imessage(phone: str, message: str):
    """Send iMessage via Series API."""
    try:
        response = requests.post(
            f"{SERIES_BASE_URL}/messaging/send",
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": SERIES_API_KEY
            },
            json={
                "to": phone,
                "message": message
            },
            timeout=30
        )
        logger.info(f"iMessage to {phone}: {response.status_code}")
        return response.ok
    except Exception as e:
        logger.error(f"iMessage failed: {e}")
        return False


# Simulation endpoints for testing
@app.route('/simulate/participant-joined', methods=['POST'])
def simulate_participant_joined():
    """Simulate a participant joining (for testing without real calls)."""
    data = request.get_json()
    conference_name = data.get('conference_name')
    phone = data.get('phone')

    logger.info(f"[SIMULATION] Participant {phone} joined {conference_name}")
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    print("=" * 50)
    print("Series Webhook Server (Simplified)")
    print("=" * 50)
    print(f"Listening on port {WEBHOOK_PORT}")
    print(f"NGROK_URL: {NGROK_URL}")
    print("=" * 50)

    app.run(host='0.0.0.0', port=WEBHOOK_PORT)
