import logging
import time
import uuid
import os
import requests
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.series_api import SeriesAPI
    from services.twilio_service import TwilioService

logger = logging.getLogger(__name__)

# Webhook server URL (set via environment)
WEBHOOK_URL = os.getenv('NGROK_URL', '')

# SIMULATION MODE - Set to True to simulate Raiymbek's phone
# When enabled:
# - Raiymbek auto-joins waitroom when you text "call"
# - Raiymbek auto-accepts the match
# - Only your phone gets called (Raiymbek's phone is skipped)
# - AI features still work (intro + icebreakers play to your call)
SIMULATION_MODE = True
SIMULATED_PHONE = '+17186030712'  # Raiymbek's phone (won't be called)
REAL_PHONE = '+19297283369'  # Ali's phone (will be called)

# User profiles (hardcoded for hackathon demo)
USER_PROFILES = {
    '+19297283369': {
        'name': 'Ali Bauyrzhan',
        'title': 'Mathematics-Statistics @ Columbia University',
        'bio': 'Building voice-driven development tools. CV Engineer @ Eulerion. Presented on hosting LLM projects at DevFest 2023.',
        'interests': 'Deep Learning, NLP, Voice AI, LLMs'
    },
    '+17186030712': {
        'name': 'Raiymbek Kokteubay',
        'title': 'CV/ML Engineer @ Eulerion | Data Science @ Columbia',
        'bio': '5th place at Jane Street x GPU MODE Hackathon. Built real-time video analytics with YOLOv8.',
        'interests': 'Computer Vision, ML Performance, PyTorch, YOLO'
    }
}

MATCH_TIMEOUT_SECONDS = 300  # 5 minutes

# Greeting patterns (case-insensitive)
GREETINGS = {'hi', 'hello', 'hey', 'sup', 'yo', 'hola', 'whatsup', "what's up", 'howdy'}

# Command definitions
COMMANDS = {
    'call': 'Enter the waitroom to find a call group',
    'leave': 'Leave the waitroom',
    'status': 'Check your waitroom status',
    'list': 'See who else is in the waitroom',
    'help': 'Show available commands',
}

HELP_TEXT = """Welcome to Series Live!

Commands:
• Call - Enter the waitroom to find a call group
• Leave - Exit the waitroom
• Status - Check if you're in the waitroom
• List - See who's waiting
• Help - Show this message

Just text any command to get started!"""

GREETING_RESPONSE = [
    "Hey there! Welcome to Series Live!",
    "I can help you to set you up on a phone call with people.",
    "Text Call to enter the waitroom and get matched with others for a group call."
]


class WaitRoom:
    """Simple in-memory waitroom for matchmaking."""

    def __init__(self):
        self.users = {}  # phone -> {chat_id, joined_at, name}

    def join(self, phone: str, chat_id: str, name: str = None) -> tuple[bool, str]:
        """Add user to waitroom. Returns (success, message)."""
        if phone in self.users:
            return False, "You're already in the waitroom! Text STATUS to check."

        self.users[phone] = {
            'chat_id': chat_id,
            'joined_at': time.time(),
            'name': name or phone[-4:]  # Last 4 digits as default name
        }

        count = len(self.users)
        return True, f"You've joined the waitroom! ({count} {'person' if count == 1 else 'people'} waiting)\n\nWe'll notify you when there are enough people for a call."

    def leave(self, phone: str) -> tuple[bool, str]:
        """Remove user from waitroom. Returns (success, message)."""
        if phone not in self.users:
            return False, "You're not in the waitroom. Text JOIN to enter."

        del self.users[phone]
        return True, "You've left the waitroom. Text JOIN anytime to come back!"

    def status(self, phone: str) -> str:
        """Check user's waitroom status."""
        if phone in self.users:
            user = self.users[phone]
            wait_time = int(time.time() - user['joined_at'])
            mins = wait_time // 60
            secs = wait_time % 60
            return f"You're in the waitroom!\nWaiting: {mins}m {secs}s\nPeople waiting: {len(self.users)}"
        else:
            return f"You're not in the waitroom.\nPeople waiting: {len(self.users)}\n\nText JOIN to enter!"

    def list_users(self, exclude_phone: str = None) -> str:
        """List users in waitroom."""
        if not self.users:
            return "The waitroom is empty. Be the first to JOIN!"

        count = len(self.users)
        names = [u['name'] for p, u in self.users.items() if p != exclude_phone]

        if not names:
            return f"Just you in the waitroom! ({count} total)"

        names_str = ", ".join(names[:5])
        if len(names) > 5:
            names_str += f" and {len(names) - 5} more"

        return f"Waitroom ({count} {'person' if count == 1 else 'people'}):\n{names_str}"

    def get_ready_group(self, min_size: int = 2) -> list | None:
        """Check if we have enough people for a call. Returns list of users or None."""
        if len(self.users) >= min_size:
            # Return all users as a group
            return list(self.users.items())
        return None

    def clear_users(self, phones: list[str]):
        """Remove multiple users from waitroom (after matching)."""
        for phone in phones:
            self.users.pop(phone, None)


class MessageHandler:
    """Handler for incoming Series API events."""

    def __init__(self, series_api: "SeriesAPI", twilio_service: "TwilioService"):
        self.series = series_api
        self.twilio = twilio_service
        self.active_chats = {}  # phone -> chat_id mapping
        self.waitroom = WaitRoom()
        self.pending_matches = {}  # match_id -> {phones, responses, created_at, chat_ids}

    def handle_event(self, event: dict):
        """Route events to appropriate handlers."""
        event_type = event.get('event_type')

        if event_type == 'message.received':
            self.handle_message(event.get('data', {}))
        elif event_type == 'typing_indicator.received':
            self.handle_typing_start(event.get('data', {}))
        elif event_type == 'typing_indicator.removed':
            self.handle_typing_stop(event.get('data', {}))
        else:
            logger.warning(f"Unknown event type: {event_type}")

    def handle_message(self, data: dict):
        """Handle incoming message with command parsing."""
        from_phone = data.get('from_phone')
        text = data.get('text', '').strip()
        chat_id = data.get('chat_id')
        message_id = data.get('id')

        logger.info(f"Message from {from_phone}: {text}")

        # Check for expired matches on each message
        self.check_expired_matches()

        # Store chat mapping
        if from_phone and chat_id:
            self.active_chats[from_phone] = chat_id

        # Skip empty messages
        if not text or not chat_id:
            logger.debug("Skipping empty message or missing chat_id")
            return

        # Parse and handle command/message
        response = self.process_message(from_phone, text, chat_id)

        # Send reply (supports single string or list of strings)
        if response:
            messages = response if isinstance(response, list) else [response]
            for msg in messages:
                try:
                    logger.info(f"Sending to chat {chat_id}: {msg[:50]}...")
                    result = self.series.send_message(int(chat_id), msg)
                    logger.info(f"Sent reply to chat {chat_id}, message_id: {result.get('data', {}).get('id')}")
                except Exception as e:
                    logger.error(f"Failed to send reply: {e}")

    def process_message(self, phone: str, text: str, chat_id: str) -> str | list[str]:
        """Process message and return response (string or list of strings for multiple messages)."""
        text_lower = text.lower().strip()

        # Check for greetings
        if text_lower in GREETINGS:
            return GREETING_RESPONSE  # Returns list for multiple messages

        # Check for Yes/No responses (for pending matches)
        if text_lower in ('yes', 'y'):
            return self.handle_match_response(phone, chat_id, 'yes')

        if text_lower in ('no', 'n'):
            return self.handle_match_response(phone, chat_id, 'no')

        # Check for commands
        if text_lower == 'help':
            return HELP_TEXT

        if text_lower == 'call':
            success, msg = self.waitroom.join(phone, chat_id)
            if success:
                # SIMULATION MODE: Auto-add simulated user to waitroom
                if SIMULATION_MODE and phone == REAL_PHONE:
                    logger.info(f"[SIMULATION] Auto-joining {SIMULATED_PHONE} to waitroom")
                    sim_profile = USER_PROFILES.get(SIMULATED_PHONE, {})
                    self.waitroom.join(
                        SIMULATED_PHONE,
                        'sim-chat-id',  # Fake chat ID for simulated user
                        sim_profile.get('name', 'Simulated User')
                    )
                self.check_for_match()
            return msg

        if text_lower == 'leave':
            _, msg = self.waitroom.leave(phone)
            return msg

        if text_lower == 'status':
            return self.waitroom.status(phone)

        if text_lower == 'list':
            return self.waitroom.list_users(exclude_phone=phone)

        # Unknown command - show help hint
        return f"I didn't understand that. Text Help to see available commands."

    def check_for_match(self, min_size: int = 2):
        """Check if we have enough people to start a call. Sends confirmation requests."""
        group = self.waitroom.get_ready_group(min_size)

        if group:
            logger.info(f"Match found! {len(group)} people ready for call")

            # Create a pending match
            match_id = str(uuid.uuid4())[:8]
            phones = [phone for phone, _ in group]
            chat_ids = {phone: user_data['chat_id'] for phone, user_data in group}

            self.pending_matches[match_id] = {
                'phones': phones,
                'chat_ids': chat_ids,
                'responses': {},  # phone -> 'yes' | 'no'
                'created_at': time.time()
            }

            # Clear matched users from waitroom (they're now in pending match)
            self.waitroom.clear_users(phones)

            # Send profile summary and confirmation request to each user
            for phone, user_data in group:
                chat_id = user_data['chat_id']

                # SIMULATION MODE: Auto-accept for simulated user
                if SIMULATION_MODE and phone == SIMULATED_PHONE:
                    logger.info(f"[SIMULATION] Auto-accepting match for {phone}")
                    self.pending_matches[match_id]['responses'][phone] = 'yes'
                    self.active_chats[f"{phone}_pending_match"] = match_id
                    continue  # Skip sending message to simulated user

                # Get the other person's profile
                other_phone = [p for p in phones if p != phone][0]
                other_profile = USER_PROFILES.get(other_phone, {})

                other_name = other_profile.get('name', other_phone[-4:])
                other_title = other_profile.get('title', '')
                other_bio = other_profile.get('bio', '')
                other_interests = other_profile.get('interests', '')

                # Build profile message
                msg = f"Match found! Here's who wants to connect:\n\n"
                msg += f"{other_name}\n"
                if other_title:
                    msg += f"{other_title}\n"
                if other_bio:
                    msg += f"{other_bio}\n"
                if other_interests:
                    msg += f"Interests: {other_interests}\n"
                msg += f"\nReply 'Yes' to connect or 'No' to skip. (5 min to respond)"

                # Store match_id for this user
                self.active_chats[f"{phone}_pending_match"] = match_id

                try:
                    self.series.send_message(int(chat_id), msg)
                    logger.info(f"Sent match confirmation to {phone}")
                except Exception as e:
                    logger.error(f"Failed to send match confirmation to {phone}: {e}")

    def handle_match_response(self, phone: str, chat_id: str, response: str) -> str:
        """Handle Yes/No response to a pending match."""
        # Find the pending match for this user
        match_id = self.active_chats.get(f"{phone}_pending_match")

        if not match_id or match_id not in self.pending_matches:
            return "You don't have a pending match. Text Call to join the waitroom!"

        match = self.pending_matches[match_id]

        # Record the response
        match['responses'][phone] = response
        logger.info(f"{phone} responded '{response}' to match {match_id}")

        if response == 'no':
            # Cancel the match
            return self.cancel_match(match_id, phone, "declined")

        # Response is 'yes' - check if everyone confirmed
        all_phones = match['phones']

        # Notify the other person that this user is waiting
        other_phone = [p for p in all_phones if p != phone][0]
        if other_phone not in match['responses']:
            # Other person hasn't responded yet - nudge them
            other_chat_id = match['chat_ids'].get(other_phone)
            my_profile = USER_PROFILES.get(phone, {})
            my_name = my_profile.get('name', 'Your match')
            if other_chat_id:
                try:
                    self.series.send_message(int(other_chat_id), f"{my_name} is waiting for you! Reply Yes or No.")
                except Exception as e:
                    logger.error(f"Failed to notify {other_phone}: {e}")

        all_responded = all(p in match['responses'] for p in all_phones)
        all_yes = all(match['responses'].get(p) == 'yes' for p in all_phones)

        if all_responded and all_yes:
            # Everyone said yes! Initiate the call
            return self.initiate_call(match_id)
        else:
            # Still waiting for other person
            other_phone = [p for p in all_phones if p != phone][0]
            other_profile = USER_PROFILES.get(other_phone, {})
            other_name = other_profile.get('name', 'your match')
            return f"You're in! Waiting for {other_name} to confirm..."

    def cancel_match(self, match_id: str, decliner_phone: str, reason: str) -> str:
        """Cancel a pending match and return users to waitroom."""
        if match_id not in self.pending_matches:
            return "Match not found."

        match = self.pending_matches[match_id]
        phones = match['phones']
        chat_ids = match['chat_ids']

        # Notify the other user(s)
        for phone in phones:
            # Clean up pending match reference
            self.active_chats.pop(f"{phone}_pending_match", None)

            if phone != decliner_phone:
                other_chat_id = chat_ids.get(phone)
                if other_chat_id:
                    if reason == "declined":
                        msg = "Your match declined. You've been returned to the waitroom.\n\nWe'll notify you when there's another match!"
                    else:  # timeout
                        msg = "Match expired (no response in 5 minutes). You've been returned to the waitroom."
                    try:
                        self.series.send_message(int(other_chat_id), msg)
                    except Exception as e:
                        logger.error(f"Failed to notify {phone} of cancellation: {e}")

                # Return to waitroom
                self.waitroom.join(phone, other_chat_id)

        # Clean up the match
        del self.pending_matches[match_id]

        if reason == "declined":
            return "Match cancelled. You've been returned to the waitroom."
        else:
            return "Match expired."

    def initiate_call(self, match_id: str) -> str:
        """Initiate a Twilio conference call for a confirmed match."""
        if match_id not in self.pending_matches:
            return "Match not found."

        match = self.pending_matches[match_id]
        phones = match['phones']
        chat_ids = match['chat_ids']

        logger.info(f"Initiating call for match {match_id} with {phones}")

        # Notify all users that call is starting
        for phone in phones:
            chat_id = chat_ids.get(phone)
            # Clean up pending match reference
            self.active_chats.pop(f"{phone}_pending_match", None)

            if chat_id and phone != phones[-1]:  # Don't send to last person (they get return message)
                try:
                    self.series.send_message(int(chat_id), "Both confirmed! Calling you now...")
                except Exception as e:
                    logger.error(f"Failed to notify {phone}: {e}")

        # Clean up the match
        del self.pending_matches[match_id]

        # Check if Twilio is configured
        if not hasattr(self.twilio, 'add_participant'):
            logger.warning("Twilio not configured - cannot start conference")
            return "Both confirmed! (Twilio not configured for demo)"

        # Start the conference call
        conference_name = f"series-match-{int(time.time())}"
        self.twilio.create_conference(conference_name)

        # Get webhook URL from environment
        webhook_url = os.getenv('NGROK_URL', '')

        # If webhook server is configured, register the conference with profiles
        if webhook_url:
            try:
                # Build profiles dict for the webhook server
                profiles = {}
                for phone in phones:
                    profiles[phone] = USER_PROFILES.get(phone, {
                        'name': phone[-4:],
                        'title': '',
                        'bio': '',
                        'interests': ''
                    })

                # Register conference with webhook server
                response = requests.post(
                    f"{webhook_url}/conference/create",
                    json={
                        'conference_name': conference_name,
                        'profiles': profiles
                    },
                    timeout=5
                )
                if response.ok:
                    logger.info(f"Registered conference {conference_name} with webhook server")
                else:
                    logger.warning(f"Failed to register conference: {response.text}")
                    webhook_url = ''  # Fallback to basic mode

            except Exception as e:
                logger.error(f"Failed to contact webhook server: {e}")
                webhook_url = ''  # Fallback to basic mode

        # Call each participant
        for phone in phones:
            # SIMULATION MODE: Skip calling simulated phone
            if SIMULATION_MODE and phone == SIMULATED_PHONE:
                logger.info(f"[SIMULATION] Skipping call to {phone} (simulated)")
                # Simulate participant joining the conference
                if webhook_url:
                    try:
                        requests.post(
                            f"{webhook_url}/simulate/participant-joined",
                            json={
                                'conference_name': conference_name,
                                'phone': phone,
                                'simulated': True
                            },
                            timeout=5
                        )
                        logger.info(f"[SIMULATION] Notified webhook server of simulated join for {phone}")
                    except Exception as e:
                        logger.error(f"[SIMULATION] Failed to notify webhook: {e}")
                continue

            try:
                # Use webhook URL for proper status callbacks
                ngrok_url = os.getenv('NGROK_URL')
                call_sid = self.twilio.add_participant(
                    conference_name,
                    phone,
                    webhook_base_url=ngrok_url  # Enable webhook for status callbacks
                )
                logger.info(f"Calling {phone} (Call SID: {call_sid})")
            except Exception as e:
                logger.error(f"Failed to call {phone}: {e}")

        return "Both confirmed! Calling you now..."

    def check_expired_matches(self):
        """Check for and handle expired pending matches."""
        current_time = time.time()
        expired = []

        for match_id, match in self.pending_matches.items():
            if current_time - match['created_at'] > MATCH_TIMEOUT_SECONDS:
                expired.append(match_id)

        for match_id in expired:
            logger.info(f"Match {match_id} expired")
            # Find any user who didn't respond to use as the "decliner"
            match = self.pending_matches[match_id]
            for phone in match['phones']:
                if phone not in match['responses']:
                    self.cancel_match(match_id, phone, "timeout")
                    break

    def handle_typing_start(self, data: dict):
        """Handle typing indicator started event."""
        chat_id = data.get('chat_id')
        logger.debug(f"Typing started in chat {chat_id}")

    def handle_typing_stop(self, data: dict):
        """Handle typing indicator stopped event."""
        chat_id = data.get('chat_id')
        logger.debug(f"Typing stopped in chat {chat_id}")

    def get_chat_id_for_phone(self, phone_number: str) -> int | None:
        """Get the chat ID for a phone number if we've seen it before."""
        return self.active_chats.get(phone_number)

    def send_to_phone(self, phone_number: str, message: str) -> bool:
        """Send a message to a phone number."""
        chat_id = self.active_chats.get(phone_number)

        try:
            if chat_id:
                self.series.send_message(int(chat_id), message)
            else:
                result = self.series.create_chat([phone_number], message)
                if result and 'id' in result:
                    self.active_chats[phone_number] = result['id']
            return True
        except Exception as e:
            logger.error(f"Failed to send to {phone_number}: {e}")
            return False
