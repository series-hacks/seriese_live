import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)


class SeriesAPI:
    """Client for Series API (iMessage integration)."""

    def __init__(self, api_key: str, base_url: str, sender_number: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.sender_number = sender_number
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def create_chat(
        self,
        phone_numbers: list[str],
        message: str,
        display_name: Optional[str] = None
    ) -> dict:
        """
        Create a new chat and send initial message.

        Args:
            phone_numbers: List of E.164 formatted phone numbers
            message: Initial message text
            display_name: Optional display name for group chats

        Returns:
            Chat object with id for future messages
        """
        url = f"{self.base_url}/api/chats"
        payload = {
            "send_from": self.sender_number,
            "chat": {"phone_numbers": phone_numbers},
            "message": {"text": message}
        }

        if display_name:
            payload["chat"]["display_name"] = display_name

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to create chat: {e}")
            raise

    def send_message(
        self,
        chat_id: int,
        text: str,
        attachments: Optional[list] = None
    ) -> dict:
        """
        Send a message to an existing chat.

        Args:
            chat_id: The chat ID to send to
            text: Message text
            attachments: Optional list of attachment URLs

        Returns:
            Message object
        """
        url = f"{self.base_url}/api/chats/{chat_id}/chat_messages"
        payload = {"message": {"text": text}}

        if attachments:
            payload["message"]["attachments"] = attachments

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to send message to chat {chat_id}: {e}")
            raise

    def get_chat(self, chat_id: int) -> dict:
        """
        Get chat details by ID.

        Args:
            chat_id: The chat ID

        Returns:
            Chat object
        """
        url = f"{self.base_url}/api/chats/{chat_id}"

        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get chat {chat_id}: {e}")
            raise

    def list_chats(
        self,
        phone_number: Optional[str] = None,
        page: int = 1,
        per_page: int = 25
    ) -> dict:
        """
        List chats with optional filters.

        Args:
            phone_number: Filter by phone number
            page: Page number
            per_page: Results per page

        Returns:
            Paginated list of chats
        """
        url = f"{self.base_url}/api/chats"
        params = {"page": page, "per_page": per_page}

        if phone_number:
            params["phone_number"] = phone_number

        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to list chats: {e}")
            raise

    def start_typing(self, chat_id: int) -> None:
        """
        Send typing indicator to a chat.

        Args:
            chat_id: The chat ID
        """
        url = f"{self.base_url}/api/chats/{chat_id}/start_typing"

        try:
            response = requests.post(url, headers=self.headers)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to start typing in chat {chat_id}: {e}")
            raise

    def stop_typing(self, chat_id: int) -> None:
        """
        Remove typing indicator from a chat.

        Args:
            chat_id: The chat ID
        """
        url = f"{self.base_url}/api/chats/{chat_id}/stop_typing"

        try:
            response = requests.delete(url, headers=self.headers)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to stop typing in chat {chat_id}: {e}")
            raise

    def add_reaction(
        self,
        message_id: int,
        reaction_type: str,
        operation: str = "add"
    ) -> dict:
        """
        Add or remove a reaction to a message.

        Args:
            message_id: The message ID
            reaction_type: One of: love, like, dislike, laugh, emphasize, question
            operation: "add" or "remove"

        Returns:
            Reaction response
        """
        url = f"{self.base_url}/api/chat_messages/{message_id}/reactions"
        payload = {
            "reaction_type": reaction_type,
            "operation": operation
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to add reaction to message {message_id}: {e}")
            raise

    def mark_as_read(self, chat_id: int) -> None:
        """
        Mark a chat as read.

        Args:
            chat_id: The chat ID
        """
        url = f"{self.base_url}/api/chats/{chat_id}/mark_as_read"

        try:
            response = requests.put(url, headers=self.headers)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to mark chat {chat_id} as read: {e}")
            raise

    def check_imessage_availability(self, phone_number: str) -> dict:
        """
        Check if a phone number can receive iMessages.

        Args:
            phone_number: E.164 formatted phone number

        Returns:
            Availability status
        """
        url = f"{self.base_url}/api/i_message_availability/check"
        payload = {"phone_number": phone_number}

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to check iMessage availability for {phone_number}: {e}")
            raise
