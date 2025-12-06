import logging
import time
import base64
import audioop
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class SilenceDetector:
    """
    Detect silence in Twilio Media Stream audio.

    Twilio Media Streams send audio as:
    - Format: mulaw (u-law) encoded
    - Sample rate: 8000 Hz
    - Channels: 1 (mono)
    - Base64 encoded in JSON messages
    """

    def __init__(
        self,
        threshold_seconds: float = 5.0,
        energy_threshold: int = 500,
        on_silence_callback: Optional[Callable] = None
    ):
        """
        Initialize silence detector.

        Args:
            threshold_seconds: Seconds of silence before triggering callback
            energy_threshold: Audio energy level below which is considered silence
            on_silence_callback: Function to call when silence threshold is exceeded
        """
        self.threshold_seconds = threshold_seconds
        self.energy_threshold = energy_threshold
        self.on_silence_callback = on_silence_callback

        self.last_speech_time = time.time()
        self.silence_triggered = False
        self.is_playing_audio = False  # Don't detect silence while playing TTS

    def process_audio(self, payload: str) -> bool:
        """
        Process base64-encoded mulaw audio payload from Twilio Media Stream.

        Args:
            payload: Base64-encoded mulaw audio data

        Returns:
            True if silence threshold was exceeded, False otherwise
        """
        # Don't process while playing TTS audio
        if self.is_playing_audio:
            return False

        try:
            # Decode base64 audio
            audio_bytes = base64.b64decode(payload)

            # Convert mulaw to linear PCM for energy calculation
            # mulaw is 8-bit, converting to 16-bit linear
            pcm_audio = audioop.ulaw2lin(audio_bytes, 2)

            # Calculate RMS energy
            energy = audioop.rms(pcm_audio, 2)

            current_time = time.time()

            if energy > self.energy_threshold:
                # Speech detected
                self.last_speech_time = current_time
                self.silence_triggered = False
                return False
            else:
                # Silence detected - check if threshold exceeded
                silence_duration = current_time - self.last_speech_time

                if silence_duration >= self.threshold_seconds and not self.silence_triggered:
                    self.silence_triggered = True
                    logger.info(f"Silence detected: {silence_duration:.1f}s")

                    if self.on_silence_callback:
                        self.on_silence_callback()

                    return True

            return False

        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            return False

    def reset(self):
        """Reset the silence detector state."""
        self.last_speech_time = time.time()
        self.silence_triggered = False
        logger.debug("Silence detector reset")

    def set_playing_audio(self, is_playing: bool):
        """
        Set whether TTS audio is currently playing.
        Disables silence detection while playing.

        Args:
            is_playing: True if audio is playing, False otherwise
        """
        self.is_playing_audio = is_playing
        if not is_playing:
            # Reset timer when done playing
            self.reset()

    def get_silence_duration(self) -> float:
        """Get current silence duration in seconds."""
        return time.time() - self.last_speech_time


class ConferenceSilenceManager:
    """
    Manage silence detection for multiple participants in a conference.
    """

    def __init__(
        self,
        threshold_seconds: float = 5.0,
        on_silence_callback: Optional[Callable] = None
    ):
        """
        Initialize conference silence manager.

        Args:
            threshold_seconds: Seconds of silence from ALL participants before triggering
            on_silence_callback: Function to call when all participants are silent
        """
        self.threshold_seconds = threshold_seconds
        self.on_silence_callback = on_silence_callback
        self.participant_detectors = {}  # stream_sid -> SilenceDetector
        self.last_global_speech_time = time.time()
        self.silence_triggered = False
        self.is_playing_audio = False

    def add_participant(self, stream_sid: str):
        """Add a new participant's audio stream."""
        self.participant_detectors[stream_sid] = SilenceDetector(
            threshold_seconds=self.threshold_seconds,
            energy_threshold=500
        )
        logger.info(f"Added participant stream: {stream_sid}")

    def remove_participant(self, stream_sid: str):
        """Remove a participant's audio stream."""
        if stream_sid in self.participant_detectors:
            del self.participant_detectors[stream_sid]
            logger.info(f"Removed participant stream: {stream_sid}")

    def process_audio(self, stream_sid: str, payload: str) -> bool:
        """
        Process audio from a specific participant.

        Args:
            stream_sid: The stream SID of the participant
            payload: Base64-encoded audio data

        Returns:
            True if global silence threshold was exceeded
        """
        if self.is_playing_audio:
            return False

        if stream_sid not in self.participant_detectors:
            self.add_participant(stream_sid)

        detector = self.participant_detectors[stream_sid]

        try:
            audio_bytes = base64.b64decode(payload)
            pcm_audio = audioop.ulaw2lin(audio_bytes, 2)
            energy = audioop.rms(pcm_audio, 2)

            current_time = time.time()

            if energy > 500:
                # Someone is speaking
                self.last_global_speech_time = current_time
                self.silence_triggered = False
                return False

            # Check global silence
            silence_duration = current_time - self.last_global_speech_time

            if silence_duration >= self.threshold_seconds and not self.silence_triggered:
                self.silence_triggered = True
                logger.info(f"Global silence detected: {silence_duration:.1f}s")

                if self.on_silence_callback:
                    self.on_silence_callback()

                return True

            return False

        except Exception as e:
            logger.error(f"Error processing audio from {stream_sid}: {e}")
            return False

    def reset(self):
        """Reset all silence detection state."""
        self.last_global_speech_time = time.time()
        self.silence_triggered = False
        for detector in self.participant_detectors.values():
            detector.reset()

    def set_playing_audio(self, is_playing: bool):
        """Set whether TTS audio is currently playing."""
        self.is_playing_audio = is_playing
        for detector in self.participant_detectors.values():
            detector.set_playing_audio(is_playing)
        if not is_playing:
            self.reset()
