import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


class HathoraTTS:
    """Text-to-Speech service using Hathora API."""

    BASE_URL = "https://app-01312daf-6e53-4b9d-a4ad-13039f35adc4.app.hathora.dev"

    def __init__(self, auth_token: str):
        """
        Initialize Hathora TTS service.

        Args:
            auth_token: Bearer token for authentication
        """
        self.auth_token = auth_token
        self.headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }

    def synthesize(
        self,
        text: str,
        voice: str = "am_adam",
        speed: float = 0.8
    ) -> Optional[bytes]:
        """
        Synthesize speech from text.

        Args:
            text: Text to convert to speech
            voice: Voice to use (default: bf_isabella)
            speed: Speech speed (default: 0.8)

        Returns:
            Audio bytes (WAV/MP3) or None if failed
        """
        try:
            response = requests.post(
                f"{self.BASE_URL}/synthesize",
                headers=self.headers,
                json={
                    "text": text,
                    "voice": voice,
                    "speed": speed
                },
                timeout=30
            )

            if response.ok:
                logger.info(f"TTS synthesized: {text[:50]}...")
                return response.content
            else:
                logger.error(f"TTS failed: {response.status_code} - {response.text}")
                return None

        except requests.RequestException as e:
            logger.error(f"TTS request failed: {e}")
            return None

    def synthesize_to_file(
        self,
        text: str,
        output_path: str,
        voice: str = "am_adam",
        speed: float = 0.8
    ) -> bool:
        """
        Synthesize speech and save to file.

        Args:
            text: Text to convert to speech
            output_path: Path to save audio file
            voice: Voice to use
            speed: Speech speed

        Returns:
            True if successful, False otherwise
        """
        audio_bytes = self.synthesize(text, voice, speed)
        if audio_bytes:
            try:
                with open(output_path, 'wb') as f:
                    f.write(audio_bytes)
                logger.info(f"Audio saved to {output_path}")
                return True
            except IOError as e:
                logger.error(f"Failed to save audio: {e}")
                return False
        return False
