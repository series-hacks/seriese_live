import logging
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)


class IcebreakerAI:
    """OpenAI-powered icebreaker question generator."""

    def __init__(self, api_key: str):
        """
        Initialize the icebreaker AI service.

        Args:
            api_key: OpenAI API key
        """
        self.client = OpenAI(api_key=api_key)
        self.conversation_history = {}  # conference_name -> list of previous icebreakers

    def generate_introduction(self, profile1: dict, profile2: dict) -> str:
        """
        Generate a short spoken introduction for both users at call start.

        Args:
            profile1: First user's profile {name, title, bio, interests}
            profile2: Second user's profile {name, title, bio, interests}

        Returns:
            Short introduction text for TTS
        """
        prompt = f"""Generate a brief, friendly spoken introduction for a phone call between two people.
Keep it SHORT (under 30 words) and conversational. Don't use bullet points.

Person 1:
- Name: {profile1.get('name', 'Unknown')}
- Title: {profile1.get('title', '')}
- Interests: {profile1.get('interests', '')}

Person 2:
- Name: {profile2.get('name', 'Unknown')}
- Title: {profile2.get('title', '')}
- Interests: {profile2.get('interests', '')}

Format: "Hey! You're now connected. [One sentence about person 1]. [One sentence about person 2]. [Mention what they have in common]."
"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a friendly call host. Keep responses very short and natural for spoken text."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0.7
            )
            intro = response.choices[0].message.content.strip()
            logger.info(f"Generated introduction: {intro}")
            return intro

        except Exception as e:
            logger.error(f"Failed to generate introduction: {e}")
            # Fallback intro
            name1 = profile1.get('name', 'your match')
            name2 = profile2.get('name', 'your match')
            return f"Hey! You're now connected. {name1}, meet {name2}."

    def generate_icebreaker(
        self,
        profile1: dict,
        profile2: dict,
        conference_name: str,
        previous_questions: Optional[list] = None
    ) -> str:
        """
        Generate a contextual, humorous icebreaker question.

        Args:
            profile1: First user's profile
            profile2: Second user's profile
            conference_name: Conference identifier for tracking history
            previous_questions: List of previously asked questions (optional)

        Returns:
            Icebreaker question text for TTS
        """
        # Get or initialize conversation history
        if conference_name not in self.conversation_history:
            self.conversation_history[conference_name] = []

        history = self.conversation_history[conference_name]
        if previous_questions:
            history.extend(previous_questions)

        # Build context about previous questions to avoid
        avoid_context = ""
        if history:
            avoid_context = f"\n\nPreviously asked questions (don't repeat these themes):\n" + "\n".join(f"- {q}" for q in history[-5:])

        prompt = f"""Generate ONE fun, casual icebreaker question for two people on a call.
The question should be:
- Humorous but not awkward
- Related to their shared interests if possible
- Easy to answer quickly
- Conversational and natural when spoken

Person 1:
- Name: {profile1.get('name', 'Unknown')}
- Background: {profile1.get('bio', '')}
- Interests: {profile1.get('interests', '')}

Person 2:
- Name: {profile2.get('name', 'Unknown')}
- Background: {profile2.get('bio', '')}
- Interests: {profile2.get('interests', '')}
{avoid_context}

Output ONLY the question, nothing else. Make it fun and engaging!"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a witty conversation facilitator. Generate fun, light-hearted questions."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=60,
                temperature=0.9
            )
            question = response.choices[0].message.content.strip()

            # Store in history
            self.conversation_history[conference_name].append(question)

            logger.info(f"Generated icebreaker: {question}")
            return question

        except Exception as e:
            logger.error(f"Failed to generate icebreaker: {e}")
            # Fallback questions
            fallbacks = [
                "What's the most interesting project you've worked on recently?",
                "If you could have any superpower for coding, what would it be?",
                "What's your hot take on AI right now?",
                "Coffee or energy drinks - what powers your coding sessions?",
                "What's the weirdest bug you've ever encountered?"
            ]
            import random
            return random.choice(fallbacks)

    def generate_follow_up(
        self,
        profile1: dict,
        profile2: dict,
        topic: str
    ) -> str:
        """
        Generate a follow-up question based on the current topic.

        Args:
            profile1: First user's profile
            profile2: Second user's profile
            topic: The current topic being discussed

        Returns:
            Follow-up question for TTS
        """
        prompt = f"""Generate a follow-up question about "{topic}" for two tech professionals.
Keep it SHORT and conversational.

Output ONLY the question."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a conversation facilitator. Keep questions short and natural."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=40,
                temperature=0.8
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"Failed to generate follow-up: {e}")
            return f"Tell me more about {topic}!"

    def clear_history(self, conference_name: str):
        """Clear conversation history for a conference."""
        if conference_name in self.conversation_history:
            del self.conversation_history[conference_name]
            logger.info(f"Cleared history for conference: {conference_name}")
