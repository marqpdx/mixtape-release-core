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

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional, List

from django.conf import settings

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class InterpretationResult:
    """Result of interpretation processing."""
    summary: str
    key_points: List[str]
    word_count: int
    method: str  # 'llm' or 'extractive'


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

    def __init__(self, use_llm: bool = True):
        """
        Initialize interpretation service.

        Args:
            use_llm: Whether to attempt LLM-based summarization
        """
        self.use_llm = use_llm
        self._llm_client = None

    def _get_llm_client(self):
        """Get OpenAI client if available."""
        if self._llm_client is not None:
            return self._llm_client

        api_key = getattr(settings, 'OPENAI_API_KEY', None) or os.getenv('OPENAI_API_KEY')
        if not api_key:
            return None

        try:
            import openai
            self._llm_client = openai.OpenAI(api_key=api_key)
            return self._llm_client
        except ImportError:
            logger.warning("OpenAI package not installed, falling back to extractive summary")
            return None

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

        # Try LLM summarization first
        if self.use_llm:
            result = self._summarize_with_llm(text, max_summary_length, extract_key_points)
            if result:
                result.word_count = word_count
                return result

        # Fallback to extractive summarization
        return self._summarize_extractive(text, max_summary_length, word_count)

    def _summarize_with_llm(
        self,
        text: str,
        max_summary_length: int,
        extract_key_points: bool,
    ) -> Optional[InterpretationResult]:
        """Generate summary using LLM."""
        client = self._get_llm_client()
        if not client:
            return None

        try:
            # Truncate text if too long (keep first ~8000 chars for context window)
            truncated_text = text[:8000] if len(text) > 8000 else text

            prompt = f"""Summarize this transcription in {max_summary_length} characters or less.
Be concise and capture the main points.

Transcription:
{truncated_text}

Provide:
1. A brief summary (2-3 sentences)
2. 3-5 key points as bullet points

Format your response as:
SUMMARY:
[your summary here]

KEY POINTS:
- [point 1]
- [point 2]
- [point 3]"""

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that summarizes audio transcriptions concisely."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.3,
            )

            content = response.choices[0].message.content

            # Parse response
            summary = ""
            key_points = []

            if "SUMMARY:" in content:
                parts = content.split("KEY POINTS:")
                summary_part = parts[0].replace("SUMMARY:", "").strip()
                summary = summary_part[:max_summary_length]

                if len(parts) > 1:
                    points_part = parts[1].strip()
                    key_points = [
                        line.strip().lstrip("- •").strip()
                        for line in points_part.split("\n")
                        if line.strip() and line.strip().startswith(("-", "•", "*"))
                    ]
            else:
                # Fallback if format not matched
                summary = content[:max_summary_length]

            return InterpretationResult(
                summary=summary,
                key_points=key_points[:5],
                word_count=0,  # Will be set by caller
                method="llm",
            )

        except Exception as e:
            logger.warning(f"LLM summarization failed: {e}")
            return None

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
    use_llm: bool = False,  # Default to extractive; inkwell will handle LLM later
) -> InterpretationResult:
    """
    Convenience function to interpret transcription text.

    Args:
        text: Transcription text
        max_summary_length: Maximum summary length
        use_llm: Whether to try LLM summarization

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
        use_llm: Whether to try LLM summarization

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
