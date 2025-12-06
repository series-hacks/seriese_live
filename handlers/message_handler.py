import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.series_api import SeriesAPI
    from services.twilio_service import TwilioService

logger = logging.getLogger(__name__)

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

        # Check for commands
        if text_lower == 'help':
            return HELP_TEXT

        if text_lower == 'call':
            success, msg = self.waitroom.join(phone, chat_id)
            if success:
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
        """Check if we have enough people to start a call."""
        group = self.waitroom.get_ready_group(min_size)

        if group:
            logger.info(f"Match found! {len(group)} people ready for call")

            # Notify all matched users
            phones = []
            for phone, user_data in group:
                phones.append(phone)
                chat_id = user_data['chat_id']

                other_names = [u['name'] for p, u in group if p != phone]
                others_str = ", ".join(other_names)

                msg = f"Match found! You're being connected with: {others_str}\n\nStandby for the call..."

                try:
                    self.series.send_message(int(chat_id), msg)
                except Exception as e:
                    logger.error(f"Failed to notify {phone}: {e}")

            # Clear matched users from waitroom
            self.waitroom.clear_users(phones)

            # Check if Twilio is configured
            if not hasattr(self.twilio, 'add_participant'):
                logger.warning("Twilio not configured - cannot start conference")
                return

            # Start the conference call
            conference_name = f"series-match-{int(time.time())}"
            self.twilio.create_conference(conference_name)

            # Call each participant and add to conference
            for phone in phones:
                try:
                    call_sid = self.twilio.add_participant(conference_name, phone)
                    logger.info(f"Calling {phone} (Call SID: {call_sid})")
                except Exception as e:
                    logger.error(f"Failed to call {phone}: {e}")

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
