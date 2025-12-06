import logging
import tempfile
import requests
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)


class Notetaker:
    """Service to transcribe and summarize call recordings."""

    def __init__(self, openai_api_key: str):
        self.client = OpenAI(api_key=openai_api_key)

    def download_recording(self, recording_url: str, auth: tuple) -> Optional[bytes]:
        """
        Download recording from Twilio.

        Args:
            recording_url: URL to the recording
            auth: Twilio auth tuple (account_sid, auth_token)

        Returns:
            Audio bytes or None if failed
        """
        try:
            # Twilio recordings are .wav by default, add .wav extension
            url = f"{recording_url}.wav"
            response = requests.get(url, auth=auth, timeout=60)
            if response.ok:
                logger.info(f"Downloaded recording: {len(response.content)} bytes")
                return response.content
            else:
                logger.error(f"Failed to download recording: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error downloading recording: {e}")
            return None

    def transcribe(self, audio_bytes: bytes) -> Optional[str]:
        """
        Transcribe audio using OpenAI Whisper.

        Args:
            audio_bytes: Audio file bytes

        Returns:
            Transcription text or None if failed
        """
        try:
            # Save to temp file for OpenAI API
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                f.write(audio_bytes)
                temp_path = f.name

            with open(temp_path, 'rb') as audio_file:
                transcription = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )

            logger.info(f"Transcribed: {len(transcription)} characters")
            return transcription

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return None

    def summarize(
        self,
        transcript: str,
        profile1: dict,
        profile2: dict
    ) -> Optional[str]:
        """
        Generate a summary of the conversation using GPT-4o-mini.

        Args:
            transcript: Full conversation transcript
            profile1: First participant's profile
            profile2: Second participant's profile

        Returns:
            Summary text or None if failed
        """
        name1 = profile1.get('name', 'Participant 1')
        name2 = profile2.get('name', 'Participant 2')

        prompt = f"""You are a meeting notetaker. Summarize this conversation between {name1} and {name2}.

Create a concise summary that includes:
1. Key topics discussed
2. Any action items or follow-ups mentioned
3. Interesting shared interests discovered
4. Potential collaboration opportunities

Keep it brief and professional (under 200 words).

Conversation transcript:
{transcript}

Summary:"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful meeting notetaker. Be concise and highlight key points."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.5
            )
            summary = response.choices[0].message.content.strip()
            logger.info(f"Generated summary: {len(summary)} characters")
            return summary

        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return None

    def process_recording(
        self,
        recording_url: str,
        auth: tuple,
        profile1: dict,
        profile2: dict
    ) -> Optional[str]:
        """
        Full pipeline: download, transcribe, summarize.

        Args:
            recording_url: Twilio recording URL
            auth: Twilio auth tuple
            profile1: First participant's profile
            profile2: Second participant's profile

        Returns:
            Summary text or None if any step failed
        """
        # Download
        audio_bytes = self.download_recording(recording_url, auth)
        if not audio_bytes:
            return None

        # Transcribe
        transcript = self.transcribe(audio_bytes)
        if not transcript:
            return None

        # Summarize
        summary = self.summarize(transcript, profile1, profile2)
        return summary
