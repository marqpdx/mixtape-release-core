# concord/services/interpretation.py
"""
Interpretation service for transcribed recordings.

Provides light summarization from transcription text.
Will be expanded to include speaker labeling, entity extraction, etc.

Usage:
    from concord.services.interpretation import interpret_transcription

    result = interpret_transcription(
        transcription_text="...",
        max_summary_length=500,
    )
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from .errors import CloudAIDisabledError


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class InterpretationResult:
    """Result of interpretation processing."""
    summary: str
    key_points: List[str]
    word_count: int
    method: str  # 'extractive' or 'none'


# ============================================================================
# Interpretation Service
# ============================================================================

class InterpretationService:
    """
    Service for interpreting transcriptions.

    Currently provides:
    - Light summarization from first few paragraphs

    Future expansion:
    - Speaker labeling/diarization
    - Entity extraction (names, places, topics)
    - Action item detection
    - Sentiment analysis
    """

    def __init__(self, use_llm: bool = False):
        """Initialize local interpretation; explicit cloud requests are refused."""
        if use_llm:
            raise CloudAIDisabledError(
                "Direct cloud interpretation is disabled; use a gated Switchboard capability."
            )

    def interpret(
        self,
        text: str,
        max_summary_length: int = 500,
        extract_key_points: bool = True,
    ) -> InterpretationResult:
        """
        Interpret transcription text.

        Args:
            text: Full transcription text
            max_summary_length: Maximum characters for summary
            extract_key_points: Whether to extract key points

        Returns:
            InterpretationResult with summary and metadata
        """
        if not text or not text.strip():
            return InterpretationResult(
                summary="",
                key_points=[],
                word_count=0,
                method="none",
            )

        word_count = len(text.split())

        return self._summarize_extractive(text, max_summary_length, word_count)

    def _summarize_extractive(
        self,
        text: str,
        max_summary_length: int,
        word_count: int,
    ) -> InterpretationResult:
        """
        Generate summary using extractive method.

        Extracts the first few sentences as a summary.
        """
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())

        # Take first sentences up to max_summary_length
        summary_sentences = []
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if current_length + len(sentence) > max_summary_length:
                break

            summary_sentences.append(sentence)
            current_length += len(sentence) + 1  # +1 for space

            # Stop after 3-4 sentences for a brief summary
            if len(summary_sentences) >= 4:
                break

        summary = " ".join(summary_sentences)

        # Extract key points from first few sentences
        key_points = []
        for sentence in sentences[:5]:
            sentence = sentence.strip()
            if sentence and len(sentence) > 20:
                # Truncate long sentences
                if len(sentence) > 100:
                    sentence = sentence[:97] + "..."
                key_points.append(sentence)

        return InterpretationResult(
            summary=summary,
            key_points=key_points[:3],
            word_count=word_count,
            method="extractive",
        )


# ============================================================================
# Convenience Function
# ============================================================================

def interpret_transcription(
    text: str,
    max_summary_length: int = 500,
    use_llm: bool = False,
) -> InterpretationResult:
    """
    Convenience function to interpret transcription text.

    Args:
        text: Transcription text
        max_summary_length: Maximum summary length
        use_llm: Legacy flag; True raises CloudAIDisabledError

    Returns:
        InterpretationResult with summary and key points
    """
    service = InterpretationService(use_llm=use_llm)
    return service.interpret(text, max_summary_length=max_summary_length)


def interpret_recording(recording_id: str, use_llm: bool = False) -> InterpretationResult:
    """
    Interpret a Recording by ID.

    Gets the latest transcription and generates interpretation.

    Args:
        recording_id: Recording UUID
        use_llm: Legacy flag; True raises CloudAIDisabledError

    Returns:
        InterpretationResult

    Raises:
        Recording.DoesNotExist: If recording not found
        ValueError: If no transcription exists
    """
    from concord.models import Recording

    recording = Recording.objects.get(id=recording_id)

    # Get latest transcription
    transcription = recording.transcriptions.order_by('-version').first()
    if not transcription:
        raise ValueError(f"No transcription found for recording {recording_id}")

    return interpret_transcription(
        text=transcription.text,
        use_llm=use_llm,
    )
