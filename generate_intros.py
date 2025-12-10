#!/usr/bin/env python3
"""
Generate pre-recorded intro audio files for all profile pairs.

Usage:
    python generate_intros.py

This script generates personalized intro audio for each possible pair of users,
saving them to the static/ directory for use by the webhook server.
"""

import os
import hashlib
import itertools
from dotenv import load_dotenv

from services.icebreaker_ai import IcebreakerAI
from services.hathora_tts import HathoraTTS

# Import profiles from message handler
from handlers.message_handler import USER_PROFILES

load_dotenv()


def get_intro_filename(phone1: str, phone2: str) -> str:
    """
    Generate a consistent filename for an intro based on two phone numbers.
    Uses sorted phones to ensure same file regardless of order.
    """
    # Sort phones to ensure consistent naming
    phones = sorted([phone1, phone2])
    # Create hash of phone pair for shorter filename
    pair_hash = hashlib.md5(f"{phones[0]}_{phones[1]}".encode()).hexdigest()[:8]
    return f"intro_{pair_hash}.wav"


def generate_intros():
    """Generate intro audio files for all profile pairs."""

    # Initialize services
    openai_key = os.getenv('OPENAI_API_KEY')
    hathora_token = os.getenv('HATHORA_AUTH_TOKEN')

    if not openai_key:
        print("ERROR: OPENAI_API_KEY not set")
        return

    if not hathora_token:
        print("ERROR: HATHORA_AUTH_TOKEN not set")
        return

    ai_service = IcebreakerAI(openai_key)
    tts_service = HathoraTTS(hathora_token)

    # Ensure static directory exists
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    os.makedirs(static_dir, exist_ok=True)

    # Get all phone numbers
    phones = list(USER_PROFILES.keys())

    if len(phones) < 2:
        print("Need at least 2 profiles to generate intros")
        return

    # Generate intros for all pairs
    pairs = list(itertools.combinations(phones, 2))
    print(f"Generating intros for {len(pairs)} profile pair(s)...")

    for phone1, phone2 in pairs:
        profile1 = USER_PROFILES[phone1]
        profile2 = USER_PROFILES[phone2]

        filename = get_intro_filename(phone1, phone2)
        output_path = os.path.join(static_dir, filename)

        print(f"\n--- Generating intro for {profile1['name']} & {profile2['name']} ---")

        # Generate intro text
        print("  Generating intro text with AI...")
        intro_text = ai_service.generate_introduction(profile1, profile2)
        print(f"  Text: {intro_text}")

        # Synthesize to audio
        print("  Synthesizing audio with TTS...")
        success = tts_service.synthesize_to_file(
            text=intro_text,
            output_path=output_path,
            voice="am_adam",  # Male voice
            speed=0.85  # Slightly slower for clarity
        )

        if success:
            file_size = os.path.getsize(output_path)
            print(f"  SUCCESS: Saved to {filename} ({file_size} bytes)")
        else:
            print(f"  FAILED: Could not generate audio for {filename}")

    print("\n" + "=" * 50)
    print("Intro generation complete!")
    print(f"Files saved to: {static_dir}")
    print("\nGenerated files:")
    for f in os.listdir(static_dir):
        if f.startswith('intro_') and f.endswith('.wav'):
            print(f"  - {f}")


if __name__ == '__main__':
    generate_intros()
