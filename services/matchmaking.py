"""
Matchmaking service for Series AI.
Handles lobby matching based on semantic topic detection.
"""

import logging
import re
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Lobby:
    """Represents a lobby/host for matching."""
    name: str
    host_name: str
    host_phone: str
    tags: List[str]  # Keywords that match this lobby
    description: str


@dataclass
class MatchRecommendation:
    """Represents matchmaking recommendations for a user."""
    best_fit: Optional[Lobby]
    worst_fit: Optional[Lobby]
    user_interest: str
    best_fit_reason: str
    worst_fit_reason: str


class MatchmakingService:
    """Service for matching users to lobbies based on interests."""

    def __init__(self):
        import os
        # Lobbies loaded from environment
        self.lobbies = [
            Lobby(
                name="Gaming Session",
                host_name=os.getenv('USER2_NAME', 'Host 1'),
                host_phone=os.getenv('USER2_PHONE', '+10000000000'),
                tags=["gaming", "games", "mobile game", "playing"],
                description="Gaming session"
            ),
            Lobby(
                name="AI Discussion",
                host_name=os.getenv('USER1_NAME', 'Host 2'),
                host_phone=os.getenv('USER1_PHONE', '+10000000001'),
                tags=["ai", "startup", "artificial intelligence", "llm", "tech", "discussion"],
                description="Discussion about AI and tech"
            )
        ]

    def extract_interest(self, text: str) -> str:
        """
        Extract user interest from text message.
        
        Args:
            text: User's message text
            
        Returns:
            Extracted interest text (normalized)
        """
        # Remove common commands/words
        text_lower = text.lower().strip()
        
        # Remove common prefixes
        prefixes = ["join call", "i want to", "i want", "let's", "lets", "can we", "want to", "talk about", "discuss"]
        for prefix in prefixes:
            if text_lower.startswith(prefix):
                text_lower = text_lower[len(prefix):].strip()
        
        # Clean up
        text_lower = re.sub(r'^[^\w]+|[^\w]+$', '', text_lower)  # Remove leading/trailing non-word chars
        
        return text_lower.strip() if text_lower.strip() else text.lower().strip()

    def calculate_match_score(self, interest: str, lobby: Lobby) -> float:
        """
        Calculate semantic match score between user interest and lobby.
        Uses keyword matching with normalization.
        
        Args:
            interest: User's interest text (normalized)
            lobby: Lobby to match against
            
        Returns:
            Match score (0.0 to 1.0)
        """
        interest_lower = interest.lower()
        matches = 0
        total_checks = 0
        
        # Check each tag
        for tag in lobby.tags:
            total_checks += 1
            tag_lower = tag.lower()
            
            # Exact match
            if tag_lower == interest_lower:
                matches += 2.0  # Strong match
            # Substring match
            elif tag_lower in interest_lower or interest_lower in tag_lower:
                matches += 1.0  # Partial match
            # Word boundary match (e.g., "clash" in "clash royale")
            elif re.search(r'\b' + re.escape(tag_lower) + r'\b', interest_lower):
                matches += 1.5  # Word match
            # Check individual words
            elif any(word in tag_lower for word in interest_lower.split() if len(word) > 2):
                matches += 0.5  # Weak match
        
        if total_checks == 0:
            return 0.0
        
        # Normalize score to 0-1
        score = min(matches / (total_checks * 2.0), 1.0)
        return score

    def find_matches(self, interest: str) -> MatchRecommendation:
        """
        Find best-fit and worst-fit lobbies for a user's interest.
        
        Args:
            interest: User's interest text
            
        Returns:
            MatchRecommendation with best-fit, worst-fit, and reasons
        """
        normalized_interest = self.extract_interest(interest)
        
        # Calculate scores for each lobby
        scores = []
        for lobby in self.lobbies:
            score = self.calculate_match_score(normalized_interest, lobby)
            scores.append((lobby, score, score))
        
        # Sort by score (descending)
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Always determine best fit (even if score is low)
        best_fit = scores[0][0] if scores else None
        worst_fit = scores[-1][0] if scores and len(scores) > 1 else None
        
        # If we only have one lobby, use it as best fit
        if len(scores) == 1:
            best_fit = scores[0][0]
            worst_fit = None
        
        # Ensure we have both best and worst for contrast
        if best_fit and len(scores) > 1:
            # Use second best as worst for contrast if worst is too similar
            if worst_fit == best_fit or (scores[-1][1] > 0.5 and len(scores) > 1):
                worst_fit = scores[1][0] if len(scores) > 1 else None
        
        # Generate reasons
        best_fit_reason = ""
        if best_fit:
            if normalized_interest.lower() in best_fit.tags or any(tag in normalized_interest.lower() for tag in best_fit.tags):
                best_fit_reason = f"because you said you want to {normalized_interest}"
            else:
                best_fit_reason = f"because your interest matches {best_fit.description.lower()}"
        
        worst_fit_reason = ""
        if worst_fit and worst_fit != best_fit:
            worst_fit_reason = f"this is a poor fit, but shown for contrast"
        
        return MatchRecommendation(
            best_fit=best_fit,
            worst_fit=worst_fit,
            user_interest=normalized_interest,
            best_fit_reason=best_fit_reason,
            worst_fit_reason=worst_fit_reason
        )

    def format_recommendations(self, recommendation: MatchRecommendation) -> str:
        """
        Format matchmaking recommendations into a message.
        
        Args:
            recommendation: MatchRecommendation object
            
        Returns:
            Formatted message string
        """
        lines = ["Based on your interest, the best fit is:\n"]
        
        # Best fit option (1) - always show if available
        if recommendation.best_fit:
            lines.append(f"{recommendation.best_fit.name} call with {recommendation.best_fit.host_name} (1)")
            if recommendation.best_fit_reason:
                lines.append(f"—— {recommendation.best_fit_reason} ——")
        
        # Worst fit option (2) - only if best fit exists and they're different
        if recommendation.best_fit and recommendation.worst_fit and recommendation.worst_fit != recommendation.best_fit:
            lines.append("")
            lines.append(f"But if you want to talk about {recommendation.worst_fit.name}, join {recommendation.worst_fit.host_name} (2)")
            if recommendation.worst_fit_reason:
                lines.append(f"—— {recommendation.worst_fit_reason} ——")
        
        # Create new lobby option (3) - always available
        lines.append("")
        lines.append("Or create a new lobby (3)")
        
        return "\n".join(lines)

    def get_lobby_by_selection(self, selection: str) -> Optional[Lobby]:
        """
        Get lobby based on user selection (1, 2, or 3).
        Note: Selection 3 means create new lobby (returns None).
        
        Args:
            selection: User's selection ("1", "2", or "3")
            
        Returns:
            Lobby object or None for new lobby
        """
        if selection == "1":
            return self.lobbies[0]  # Best fit is always first in sorted order
        elif selection == "2":
            return self.lobbies[1] if len(self.lobbies) > 1 else None
        elif selection == "3":
            return None  # Create new lobby
        return None

    def get_lobby_by_host_phone(self, host_phone: str) -> Optional[Lobby]:
        """
        Get lobby by host phone number.
        
        Args:
            host_phone: Host's phone number
            
        Returns:
            Lobby object or None
        """
        for lobby in self.lobbies:
            if lobby.host_phone == host_phone:
                return lobby
        return None

    def get_lobby_by_name(self, name: str) -> Optional[Lobby]:
        """
        Get lobby by name.
        
        Args:
            name: Lobby name
            
        Returns:
            Lobby object or None
        """
        for lobby in self.lobbies:
            if lobby.name.lower() == name.lower():
                return lobby
        return None

