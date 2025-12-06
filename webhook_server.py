"""
Webhook server for Twilio Media Streams and conference events.
Handles real-time audio streaming, silence detection, and AI icebreaker generation.
"""

import os
import json
import logging
import threading
import time
import tempfile
from flask import Flask, request, Response
from flask_socketio import SocketIO
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream, Dial
from dotenv import load_dotenv

from services.hathora_tts import HathoraTTS
from services.icebreaker_ai import IcebreakerAI
from services.silence_detector import ConferenceSilenceManager
from services.notetaker import Notetaker
from services.series_api import SeriesAPI

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'series-webhook-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Twilio client
twilio_client = Client(
    os.getenv('TWILIO_ACCOUNT_SID'),
    os.getenv('TWILIO_AUTH_TOKEN')
)
TWILIO_PHONE = os.getenv('TWILIO_PHONE_NUMBER')

# Services
tts_service = HathoraTTS(os.getenv('HATHORA_AUTH_TOKEN', ''))
ai_service = IcebreakerAI(os.getenv('OPENAI_API_KEY', ''))
notetaker_service = Notetaker(os.getenv('OPENAI_API_KEY', ''))
series_api = SeriesAPI(
    api_key=os.getenv('SERIES_API_KEY', ''),
    base_url=os.getenv('SERIES_BASE_URL', ''),
    sender_number=os.getenv('SERIES_SENDER_NUMBER', '')
)

# Conference state
conferences = {}  # conference_name -> ConferenceState


class ConferenceState:
    """Track state for a single conference."""

    def __init__(self, conference_name: str, profiles: dict):
        self.conference_name = conference_name
        self.profiles = profiles  # phone -> profile dict
        self.participants = {}  # call_sid -> phone
        self.real_call_sids = {}  # phone -> call_sid (persists even after participant "leaves")
        self.stream_sids = {}  # stream_sid -> call_sid
        self.connected_count = 0
        self.intro_played = False
        self.silence_manager = ConferenceSilenceManager(
            threshold_seconds=5.0,
            on_silence_callback=lambda: self.trigger_icebreaker()
        )
        self.is_playing_tts = False
        self.icebreaker_count = 0
        self.lock = threading.Lock()

    def add_participant(self, call_sid: str, phone: str):
        """Add a participant to the conference."""
        with self.lock:
            self.participants[call_sid] = phone
            self.connected_count = len(self.participants)
            # Store real call_sid for audio playback (persists even after participant "leaves")
            if not call_sid.startswith('sim-') and phone:
                self.real_call_sids[phone] = call_sid
            logger.info(f"Participant joined {self.conference_name}: {phone} ({self.connected_count}/2)")

    def remove_participant(self, call_sid: str):
        """Remove a participant from the conference."""
        with self.lock:
            if call_sid in self.participants:
                phone = self.participants.pop(call_sid)
                self.connected_count = len(self.participants)
                logger.info(f"Participant left {self.conference_name}: {phone} ({self.connected_count}/2)")

    def all_connected(self) -> bool:
        """Check if all expected participants are connected."""
        return self.connected_count >= 2

    def trigger_icebreaker(self):
        """Generate and play an icebreaker question."""
        if self.is_playing_tts or self.icebreaker_count >= 10:  # Max 10 icebreakers per call
            return

        threading.Thread(target=self._play_icebreaker, daemon=True).start()

    def _play_icebreaker(self):
        """Background thread to generate and play icebreaker."""
        try:
            self.is_playing_tts = True
            self.silence_manager.set_playing_audio(True)

            # Get profiles
            phones = list(self.profiles.keys())
            if len(phones) < 2:
                return

            profile1 = self.profiles.get(phones[0], {})
            profile2 = self.profiles.get(phones[1], {})

            # Generate icebreaker
            question = ai_service.generate_icebreaker(
                profile1, profile2,
                self.conference_name
            )

            # Synthesize TTS
            audio_bytes = tts_service.synthesize(question)
            if audio_bytes:
                # Save to temp file and play
                self._play_audio_to_conference(audio_bytes)

            self.icebreaker_count += 1
            logger.info(f"Played icebreaker #{self.icebreaker_count}: {question}")

        except Exception as e:
            logger.error(f"Failed to play icebreaker: {e}")
        finally:
            self.is_playing_tts = False
            self.silence_manager.set_playing_audio(False)
            self.silence_manager.reset()

    def play_introduction(self):
        """Generate and play the introduction when both users connect."""
        if self.intro_played:
            return

        self.intro_played = True
        threading.Thread(target=self._play_introduction, daemon=True).start()

    def _play_introduction(self):
        """Background thread to play introduction."""
        try:
            self.is_playing_tts = True
            self.silence_manager.set_playing_audio(True)

            # Get profiles
            phones = list(self.profiles.keys())
            if len(phones) < 2:
                return

            profile1 = self.profiles.get(phones[0], {})
            profile2 = self.profiles.get(phones[1], {})

            # Generate introduction
            intro = ai_service.generate_introduction(profile1, profile2)

            # Synthesize TTS
            audio_bytes = tts_service.synthesize(intro)
            if audio_bytes:
                self._play_audio_to_conference(audio_bytes)

            logger.info(f"Played introduction for {self.conference_name}")

            # Schedule first icebreaker after 5 seconds of "silence"
            threading.Timer(5.0, self._check_and_trigger_icebreaker).start()

        except Exception as e:
            logger.error(f"Failed to play introduction: {e}")
        finally:
            self.is_playing_tts = False
            self.silence_manager.set_playing_audio(False)
            self.silence_manager.reset()

    def _check_and_trigger_icebreaker(self):
        """Check conditions and trigger icebreaker if appropriate."""
        try:
            # Only trigger if not currently playing TTS and still have participants
            if self.is_playing_tts:
                logger.info(f"Skipping icebreaker - TTS is playing")
                # Retry in 5 seconds
                threading.Timer(5.0, self._check_and_trigger_icebreaker).start()
                return

            # Check if we have at least 1 participant (simulated counts too)
            # In simulation mode, one participant may leave temporarily during audio playback
            if self.connected_count < 1:
                logger.info(f"Skipping icebreaker - no participants connected")
                return

            if self.icebreaker_count >= 10:
                logger.info(f"Max icebreakers reached for {self.conference_name}")
                return

            logger.info(f"Timer triggered icebreaker #{self.icebreaker_count + 1} for {self.conference_name}")
            self.trigger_icebreaker()

            # Schedule next icebreaker check in 15 seconds
            threading.Timer(15.0, self._check_and_trigger_icebreaker).start()

        except Exception as e:
            logger.error(f"Error in icebreaker check: {e}")

    def _play_audio_to_conference(self, audio_bytes: bytes):
        """Play audio to all participants in the conference."""
        try:
            # Save audio to temp file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                f.write(audio_bytes)
                audio_path = f.name

            ngrok_url = os.getenv('NGROK_URL', 'http://localhost:5002')
            audio_url = f"{ngrok_url}/audio/{os.path.basename(audio_path)}"

            # Play to each real participant using stored call_sids
            played_to_anyone = False
            for phone, call_sid in self.real_call_sids.items():
                try:
                    # Create TwiML that plays audio then returns to conference (waitUrl="" disables hold music)
                    play_twiml = f'''<Response><Play>{audio_url}</Play><Dial><Conference startConferenceOnEnter="true" endConferenceOnExit="false" waitUrl="">{self.conference_name}</Conference></Dial></Response>'''
                    twilio_client.calls(call_sid).update(twiml=play_twiml)
                    logger.info(f"Playing audio to {phone} via call update (call_sid: {call_sid})")
                    played_to_anyone = True
                except Exception as e:
                    logger.error(f"Failed to play audio to {call_sid}: {e}")

            if not played_to_anyone:
                logger.warning(f"No real participants to play audio to in {self.conference_name}")

            # Wait for audio to play (estimate based on file size)
            time.sleep(len(audio_bytes) / 16000)  # Rough estimate for 8kHz audio

            # Clean up temp file after delay
            try:
                os.unlink(audio_path)
            except:
                pass

        except Exception as e:
            logger.error(f"Failed to play audio: {e}")

    def _get_conference_sid(self) -> str:
        """Get the Twilio conference SID."""
        try:
            # First try in-progress status
            conference_list = twilio_client.conferences.list(
                friendly_name=self.conference_name,
                status='in-progress'
            )
            if conference_list:
                logger.info(f"Found conference {self.conference_name} with SID: {conference_list[0].sid}")
                return conference_list[0].sid

            # Log failure and try without status filter
            logger.warning(f"No in-progress conference found for: {self.conference_name}")

            # Try to find any conference with this name
            all_conferences = twilio_client.conferences.list(
                friendly_name=self.conference_name
            )
            if all_conferences:
                logger.warning(f"Found conference {self.conference_name} but status is: {all_conferences[0].status}")
                # If it's init or in-progress, we can use it
                if all_conferences[0].status in ['init', 'in-progress']:
                    return all_conferences[0].sid
            else:
                logger.warning(f"No conference found at all with name: {self.conference_name}")

        except Exception as e:
            logger.error(f"Failed to get conference SID: {e}")
        return None


# Store audio files temporarily
audio_files = {}


@app.route('/audio/<filename>', methods=['GET'])
def serve_audio(filename):
    """Serve audio file for Twilio playback."""
    audio_path = f"/tmp/{filename}"
    if os.path.exists(audio_path):
        with open(audio_path, 'rb') as f:
            return Response(f.read(), mimetype='audio/wav')
    return Response(status=404)


@app.route('/voice/answer', methods=['POST'])
def voice_answer():
    """
    Handle incoming call answer - return TwiML to join conference.
    This is called when a participant answers the call.
    """
    call_sid = request.form.get('CallSid')
    to_number = request.form.get('To')  # The number being called (participant)
    from_number = request.form.get('From')  # Twilio number
    conference_name = request.args.get('conference')

    logger.info(f"Call answered: {call_sid} to {to_number} for conference {conference_name}")

    # Store real call_sid for audio playback (before participant formally joins)
    if conference_name in conferences and to_number:
        conferences[conference_name].real_call_sids[to_number] = call_sid
        logger.info(f"Stored call_sid {call_sid} for {to_number}")

    ngrok_url = os.getenv('NGROK_URL', 'http://localhost:5002')

    response = VoiceResponse()

    # Join the conference (waitUrl="" disables hold music, record for notetaker)
    dial = Dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=False,
        wait_url='',
        record='record-from-start',
        recording_status_callback=f"{ngrok_url}/recording/complete?conference={conference_name}",
        recording_status_callback_event='completed',
        status_callback=f"{ngrok_url}/voice/status?conference={conference_name}",
        status_callback_event='join leave'
    )
    response.append(dial)

    return Response(str(response), mimetype='text/xml')


@app.route('/voice/status', methods=['POST'])
def voice_status():
    """Handle conference status callbacks (join/leave events)."""
    conference_name = request.args.get('conference')
    call_sid = request.form.get('CallSid')
    status_event = request.form.get('StatusCallbackEvent')
    from_number = request.form.get('From')

    logger.info(f"Conference status: {status_event} for {call_sid} in {conference_name}")

    if conference_name not in conferences:
        logger.warning(f"Unknown conference: {conference_name}")
        return Response(status=200)

    conf = conferences[conference_name]

    if status_event == 'participant-join':
        conf.add_participant(call_sid, from_number)

        # Check if all participants are connected
        if conf.all_connected():
            logger.info(f"All participants connected to {conference_name}!")
            conf.play_introduction()

    elif status_event == 'participant-leave':
        conf.remove_participant(call_sid)

    return Response(status=200)


@socketio.on('connect', namespace='/media-stream')
def media_connect():
    """Handle Media Stream WebSocket connection."""
    logger.info("Media stream connected")


@socketio.on('disconnect', namespace='/media-stream')
def media_disconnect():
    """Handle Media Stream WebSocket disconnection."""
    logger.info("Media stream disconnected")


@socketio.on('message', namespace='/media-stream')
def handle_media_message(message):
    """
    Handle incoming Media Stream messages from Twilio.
    Messages include 'connected', 'start', 'media', and 'stop' events.
    """
    try:
        data = json.loads(message) if isinstance(message, str) else message

        event = data.get('event')

        if event == 'connected':
            logger.info("Media stream connection established")

        elif event == 'start':
            # Media stream started
            stream_sid = data.get('streamSid')
            start_data = data.get('start', {})
            conference_name = start_data.get('customParameters', {}).get('conference')
            call_sid = start_data.get('customParameters', {}).get('callSid')

            logger.info(f"Media stream started: {stream_sid} for conference {conference_name}")

            if conference_name in conferences:
                conf = conferences[conference_name]
                conf.stream_sids[stream_sid] = call_sid
                conf.silence_manager.add_participant(stream_sid)

        elif event == 'media':
            # Audio data received
            stream_sid = data.get('streamSid')
            payload = data.get('media', {}).get('payload')

            if payload:
                # Find the conference for this stream
                for conf_name, conf in conferences.items():
                    if stream_sid in conf.stream_sids:
                        conf.silence_manager.process_audio(stream_sid, payload)
                        break

        elif event == 'stop':
            # Media stream stopped
            stream_sid = data.get('streamSid')
            logger.info(f"Media stream stopped: {stream_sid}")

            for conf in conferences.values():
                if stream_sid in conf.stream_sids:
                    conf.silence_manager.remove_participant(stream_sid)
                    del conf.stream_sids[stream_sid]
                    break

    except Exception as e:
        logger.error(f"Error handling media message: {e}")


@app.route('/conference/create', methods=['POST'])
def create_conference():
    """
    API endpoint to create a conference with user profiles.
    Called by the main bot when initiating a call.
    """
    data = request.json
    conference_name = data.get('conference_name')
    profiles = data.get('profiles', {})  # phone -> profile dict

    if not conference_name:
        return {'error': 'conference_name required'}, 400

    conferences[conference_name] = ConferenceState(conference_name, profiles)
    # Store profiles for notetaker (available after conference cleanup)
    conference_profiles[conference_name] = profiles
    logger.info(f"Created conference: {conference_name} with {len(profiles)} profiles")

    return {'status': 'ok', 'conference': conference_name}


@app.route('/conference/cleanup', methods=['POST'])
def cleanup_conference():
    """Clean up a conference after it ends."""
    data = request.json
    conference_name = data.get('conference_name')

    if conference_name in conferences:
        conf = conferences.pop(conference_name)
        ai_service.clear_history(conference_name)
        logger.info(f"Cleaned up conference: {conference_name}")

    return {'status': 'ok'}


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return {
        'status': 'healthy',
        'conferences': len(conferences),
        'ngrok_url': os.getenv('NGROK_URL', 'not set')
    }


# ============= NOTETAKER / RECORDING ENDPOINT =============

# Store conference profiles for notetaker (needed after conference cleanup)
conference_profiles = {}  # conference_name -> profiles dict


@app.route('/recording/complete', methods=['POST'])
def recording_complete():
    """
    Handle recording completion callback from Twilio.
    Downloads, transcribes, summarizes, and sends to participants via iMessage.
    """
    conference_name = request.args.get('conference')
    recording_url = request.form.get('RecordingUrl')
    recording_status = request.form.get('RecordingStatus')
    recording_sid = request.form.get('RecordingSid')

    logger.info(f"Recording complete for {conference_name}: {recording_status}, SID: {recording_sid}")

    if recording_status != 'completed':
        logger.warning(f"Recording not completed: {recording_status}")
        return Response(status=200)

    if not recording_url:
        logger.error("No recording URL in callback")
        return Response(status=200)

    # Get profiles (from active conference or stored profiles)
    profiles = None
    if conference_name in conferences:
        profiles = conferences[conference_name].profiles
    elif conference_name in conference_profiles:
        profiles = conference_profiles[conference_name]

    if not profiles or len(profiles) < 2:
        logger.error(f"No profiles found for conference {conference_name}")
        return Response(status=200)

    # Process in background thread to not block Twilio callback
    def process_and_send():
        try:
            phones = list(profiles.keys())
            profile1 = profiles.get(phones[0], {})
            profile2 = profiles.get(phones[1], {})

            # Get Twilio auth for downloading
            twilio_auth = (
                os.getenv('TWILIO_ACCOUNT_SID'),
                os.getenv('TWILIO_AUTH_TOKEN')
            )

            # Process recording: download, transcribe, summarize
            logger.info(f"Processing recording for {conference_name}...")
            summary = notetaker_service.process_recording(
                recording_url,
                twilio_auth,
                profile1,
                profile2
            )

            if not summary:
                logger.error("Failed to generate summary")
                return

            # Create personalized messages
            name1 = profile1.get('name', 'there')
            name2 = profile2.get('name', 'there')

            message_to_user1 = f"Hey {name1}! Here's a summary of your call with {name2}:\n\n{summary}"
            message_to_user2 = f"Hey {name2}! Here's a summary of your call with {name1}:\n\n{summary}"

            # Send to both participants via iMessage
            for phone, msg in [(phones[0], message_to_user1), (phones[1], message_to_user2)]:
                try:
                    series_api.create_chat(
                        phone_numbers=[phone],
                        message=msg
                    )
                    logger.info(f"Sent summary to {phone}")
                except Exception as e:
                    logger.error(f"Failed to send summary to {phone}: {e}")

            # Cleanup stored profiles
            if conference_name in conference_profiles:
                del conference_profiles[conference_name]

            logger.info(f"Notetaker complete for {conference_name}")

        except Exception as e:
            logger.error(f"Notetaker processing failed: {e}")

    # Start background processing
    thread = threading.Thread(target=process_and_send)
    thread.start()

    return Response(status=200)


# ============= SIMULATION MODE ENDPOINTS =============
# Use these to test AI features without actual phone calls

@app.route('/simulate/create', methods=['POST'])
def simulate_create():
    """
    Create a simulated conference for testing AI features.
    POST /simulate/create
    Body: {"phone1": "+1234567890", "phone2": "+0987654321"} (optional)
    """
    data = request.json or {}

    # Use provided phones or defaults
    phone1 = data.get('phone1', '+17186030712')
    phone2 = data.get('phone2', '+19297283369')

    conference_name = f"sim-conference-{int(time.time())}"

    # Get profiles from USER_PROFILES or create defaults
    from handlers.message_handler import USER_PROFILES

    profiles = {
        phone1: USER_PROFILES.get(phone1, {
            'name': 'Test User 1',
            'title': 'Software Engineer',
            'bio': 'Loves coding and AI',
            'interests': 'machine learning, python, hackathons'
        }),
        phone2: USER_PROFILES.get(phone2, {
            'name': 'Test User 2',
            'title': 'Data Scientist',
            'bio': 'Passionate about data',
            'interests': 'deep learning, NLP, startups'
        })
    }

    conferences[conference_name] = ConferenceState(conference_name, profiles)
    logger.info(f"[SIMULATION] Created conference: {conference_name}")

    return {
        'status': 'ok',
        'conference': conference_name,
        'profiles': profiles,
        'message': 'Use /simulate/join to simulate participants joining'
    }


@app.route('/simulate/join', methods=['POST'])
def simulate_join():
    """
    Simulate both participants joining the conference.
    This triggers the introduction if both are connected.
    POST /simulate/join
    Body: {"conference": "conference-name"}
    """
    data = request.json or {}
    conference_name = data.get('conference')

    if not conference_name:
        # Use the most recent conference
        if conferences:
            conference_name = list(conferences.keys())[-1]
        else:
            return {'error': 'No conference specified and no active conferences'}, 400

    if conference_name not in conferences:
        return {'error': f'Conference {conference_name} not found'}, 404

    conf = conferences[conference_name]

    # Simulate both participants joining
    phones = list(conf.profiles.keys())
    conf.add_participant('sim-call-1', phones[0] if phones else '+1111111111')
    conf.add_participant('sim-call-2', phones[1] if len(phones) > 1 else '+2222222222')

    logger.info(f"[SIMULATION] Both participants joined {conference_name}")

    # This should trigger the introduction
    if conf.all_connected():
        conf.play_introduction()
        return {
            'status': 'ok',
            'conference': conference_name,
            'message': 'Both participants joined! Introduction is being played.',
            'participants': conf.connected_count
        }

    return {
        'status': 'ok',
        'conference': conference_name,
        'participants': conf.connected_count
    }


@app.route('/simulate/silence', methods=['POST'])
def simulate_silence():
    """
    Simulate 5 seconds of silence to trigger an icebreaker.
    POST /simulate/silence
    Body: {"conference": "conference-name"}
    """
    data = request.json or {}
    conference_name = data.get('conference')

    if not conference_name:
        if conferences:
            conference_name = list(conferences.keys())[-1]
        else:
            return {'error': 'No conference specified and no active conferences'}, 400

    if conference_name not in conferences:
        return {'error': f'Conference {conference_name} not found'}, 404

    conf = conferences[conference_name]

    logger.info(f"[SIMULATION] Triggering icebreaker for {conference_name}")
    conf.trigger_icebreaker()

    return {
        'status': 'ok',
        'conference': conference_name,
        'message': 'Icebreaker triggered!',
        'icebreaker_count': conf.icebreaker_count + 1
    }


@app.route('/simulate/test-tts', methods=['POST'])
def simulate_test_tts():
    """
    Test TTS synthesis with a custom message.
    POST /simulate/test-tts
    Body: {"text": "Hello, this is a test!"}
    """
    data = request.json or {}
    text = data.get('text', 'Hello! This is a test of the text to speech system.')

    logger.info(f"[SIMULATION] Testing TTS with: {text}")

    try:
        audio_bytes = tts_service.synthesize(text)
        if audio_bytes:
            return {
                'status': 'ok',
                'text': text,
                'audio_size': len(audio_bytes),
                'message': 'TTS synthesis successful!'
            }
        else:
            return {'error': 'TTS returned no audio'}, 500
    except Exception as e:
        return {'error': str(e)}, 500


@app.route('/simulate/test-ai', methods=['POST'])
def simulate_test_ai():
    """
    Test AI icebreaker generation.
    POST /simulate/test-ai
    Body: {"type": "intro" or "icebreaker"}
    """
    data = request.json or {}
    gen_type = data.get('type', 'icebreaker')

    # Use sample profiles
    profile1 = {
        'name': 'Raiymbek',
        'title': 'CV/ML Engineer',
        'bio': '5th place at Jane Street hackathon',
        'interests': 'deep learning, computer vision'
    }
    profile2 = {
        'name': 'Ali',
        'title': 'Columbia Math Student',
        'bio': 'Working on voice AI at Eulerion',
        'interests': 'math, AI, startups'
    }

    try:
        if gen_type == 'intro':
            result = ai_service.generate_introduction(profile1, profile2)
        else:
            result = ai_service.generate_icebreaker(profile1, profile2, 'test-conference')

        return {
            'status': 'ok',
            'type': gen_type,
            'result': result
        }
    except Exception as e:
        return {'error': str(e)}, 500


@app.route('/simulate/participant-joined', methods=['POST'])
def simulate_participant_joined():
    """
    Handle a simulated participant joining a real conference.
    Called by message_handler when SIMULATION_MODE is True.
    POST /simulate/participant-joined
    Body: {"conference_name": "series-match-xxx", "phone": "+1234567890", "simulated": true}
    """
    data = request.json or {}
    conference_name = data.get('conference_name')
    phone = data.get('phone')
    simulated = data.get('simulated', False)

    if not conference_name:
        return {'error': 'conference_name required'}, 400

    if conference_name not in conferences:
        return {'error': f'Conference {conference_name} not found'}, 404

    conf = conferences[conference_name]

    # Add simulated participant
    call_sid = f"sim-{phone[-4:]}" if phone else "sim-0000"
    conf.add_participant(call_sid, phone)

    logger.info(f"[SIMULATION] Simulated participant {phone} joined {conference_name}")

    # Auto-trigger intro when all connected
    if conf.all_connected() and not conf.intro_played:
        logger.info(f"[SIMULATION] All connected! Triggering introduction for {conference_name}")
        conf.play_introduction()

    return {
        'status': 'ok',
        'conference': conference_name,
        'phone': phone,
        'simulated': simulated,
        'connected_count': conf.connected_count,
        'all_connected': conf.all_connected(),
        'intro_triggered': conf.intro_played
    }


@app.route('/simulate/status', methods=['GET'])
def simulate_status():
    """Get status of all simulated conferences."""
    status = {}
    for name, conf in conferences.items():
        status[name] = {
            'participants': conf.connected_count,
            'intro_played': conf.intro_played,
            'icebreaker_count': conf.icebreaker_count,
            'is_playing_tts': conf.is_playing_tts,
            'profiles': list(conf.profiles.keys())
        }
    return {'conferences': status}


if __name__ == '__main__':
    port = int(os.getenv('WEBHOOK_PORT', 5002))
    print("=" * 50)
    print("Series Webhook Server")
    print("=" * 50)
    print(f"Listening on port {port}")
    print(f"NGROK_URL: {os.getenv('NGROK_URL', 'NOT SET - set this before testing!')}")
    print("=" * 50)

    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
