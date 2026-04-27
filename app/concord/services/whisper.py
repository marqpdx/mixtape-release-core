# concord/services/whisper.py
"""
Whisper transcription service.

Supports multiple backends:
- faster-whisper (recommended for production - uses CTranslate2)
- OpenAI Whisper API (cloud-based)
- Local whisper model (fallback)

Usage:
    from concord.services.whisper import transcribe_audio

    result = transcribe_audio(
        audio_path="/path/to/audio.mp3",
        model_name="large-v3",
        language="en",  # optional, auto-detect if not provided
    )
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional, List

from django.conf import settings
from django.core.files.storage import default_storage

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

def _env(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name)
    return val if val not in (None, "") else default


def _detect_device(preferred: str = "auto") -> str:
    """
    Decide device for faster-whisper without requiring torch.

    Order:
      1) explicit preferred (cpu/cuda)
      2) if auto: try torch.cuda if torch exists
      3) else: cpu
    """
    preferred = (preferred or "auto").lower()

    if preferred in ("cpu", "cuda"):
        return preferred

    try:
        import torch  # optional
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass

    return "cpu"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class TranscriptSegment:
    """A segment of transcribed audio."""
    start_ms: int
    end_ms: int
    text: str
    confidence: float = 0.0
    speaker_id: Optional[str] = None  # For future diarization


@dataclass
class TranscriptionResult:
    """Result of audio transcription."""
    text: str
    language: str
    segments: List[TranscriptSegment] = field(default_factory=list)
    confidence_avg: float = 0.0
    model_name: str = ""
    backend: str = ""
    duration_ms: int = 0


# ============================================================================
# Whisper Service
# ============================================================================

class WhisperService:
    """
    Service for transcribing audio using Whisper.

    Automatically selects the best available backend:
    1. faster-whisper (if installed)
    2. OpenAI API (if API key configured)
    3. openai-whisper (if installed)
    """

    # Available model sizes
    MODEL_SIZES = ['tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3']

    def __init__(
        self,
        model_name: str = "base",
        device: str = "auto",
        compute_type: str = "auto",
    ):
        """
        Initialize Whisper service.

        Args:
            model_name: Model size (tiny, base, small, medium, large, large-v2, large-v3)
            device: Device to use (auto, cpu, cuda)
            compute_type: Compute type for faster-whisper (auto, float16, int8, etc.)
        """
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._backend = None

    def _detect_backend(self) -> str:
        """Detect the best available backend."""
        backend_override = _env("WHISPER_BACKEND")
        if backend_override:
            override = backend_override.lower()
            if override in ("faster-whisper", "faster_whisper", "faster"):
                return "faster-whisper"
            if override in ("openai-api", "openai_api", "openai"):
                return "openai-api"
            if override in ("whisper", "openai-whisper", "openai_whisper"):
                return "whisper"

        # Check for faster-whisper
        try:
            import faster_whisper
            return "faster-whisper"
        except ImportError:
            pass

        # Check for OpenAI API key
        if getattr(settings, 'OPENAI_API_KEY', None) or os.getenv('OPENAI_API_KEY'):
            try:
                import openai
                return "openai-api"
            except ImportError:
                pass

        # Check for local whisper
        try:
            import whisper
            return "whisper"
        except ImportError:
            pass

        raise ImportError(
            "No Whisper backend available. Install one of: "
            "faster-whisper, openai, or openai-whisper"
        )

    def _load_model(self):
        """Load the Whisper model (lazy loading)."""
        if self._model is not None:
            return

        self._backend = self._detect_backend()
        logger.info(f"Using Whisper backend: {self._backend}")

        if self._backend == "faster-whisper":
            self._load_faster_whisper()
        elif self._backend == "openai-api":
            self._load_openai_api()
        elif self._backend == "whisper":
            self._load_local_whisper()

    def _load_faster_whisper(self):
        """Initialize faster-whisper without requiring torch."""
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError(
                "faster-whisper backend selected but not installed. "
                "pip install faster-whisper"
            ) from e

        model_size = _env("WHISPER_MODEL_SIZE", self.model_name or "small")
        compute_type = _env("WHISPER_COMPUTE_TYPE", self.compute_type or "int8")
        device_pref = _env("WHISPER_DEVICE", self.device or "auto")

        device = _detect_device(device_pref)

        if device == "cpu" and compute_type in ("float16", "int8_float16"):
            compute_type = "int8"

        logger.info(
            "Loading faster-whisper model=%s device=%s compute_type=%s",
            model_size, device, compute_type,
        )
        self._model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
        self.model_name = model_size
        self._backend = "faster-whisper"

    def _load_openai_api(self):
        """Configure OpenAI API client."""
        import openai

        api_key = getattr(settings, 'OPENAI_API_KEY', None) or os.getenv('OPENAI_API_KEY')
        self._model = openai.OpenAI(api_key=api_key)

    def _load_local_whisper(self):
        """Load local whisper model."""
        import whisper

        device = self.device
        if device == "auto":
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info(f"Loading whisper model: {self.model_name} on {device}")
        self._model = whisper.load_model(self.model_name, device=device)

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        word_timestamps: bool = False,
    ) -> TranscriptionResult:
        """
        Transcribe audio file.

        Args:
            audio_path: Path to audio file
            language: Language code (e.g., 'en'). Auto-detect if None.
            word_timestamps: Include word-level timestamps

        Returns:
            TranscriptionResult with text, segments, and metadata
        """
        self._load_model()

        if self._backend == "faster-whisper":
            return self._transcribe_faster_whisper(audio_path, language, word_timestamps)
        elif self._backend == "openai-api":
            return self._transcribe_openai_api(audio_path, language)
        elif self._backend == "whisper":
            return self._transcribe_local_whisper(audio_path, language, word_timestamps)

    def _transcribe_faster_whisper(
        self,
        audio_path: str,
        language: Optional[str],
        word_timestamps: bool,
    ) -> TranscriptionResult:
        """Transcribe using faster-whisper."""
        segments_iter, info = self._model.transcribe(
            audio_path,
            language=language,
            word_timestamps=word_timestamps,
            vad_filter=False,
        )

        segments = []
        full_text_parts = []
        total_confidence = 0.0

        for segment in segments_iter:
            start_ms = int(segment.start * 1000)
            end_ms = int(segment.end * 1000)
            text = segment.text.strip()

            # Calculate confidence from log probability
            confidence = 1.0
            if segment.avg_logprob is not None:
                # Convert log probability to confidence (0-1 range)
                import math
                confidence = math.exp(segment.avg_logprob)
                confidence = min(max(confidence, 0.0), 1.0)

            segments.append(TranscriptSegment(
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                confidence=confidence,
            ))
            full_text_parts.append(text)
            total_confidence += confidence

        avg_confidence = total_confidence / len(segments) if segments else 0.0
        duration_ms = int(info.duration * 1000) if info.duration else 0

        return TranscriptionResult(
            text=" ".join(full_text_parts),
            language=info.language or language or "en",
            segments=segments,
            confidence_avg=avg_confidence,
            model_name=self.model_name,
            backend=self._backend or "",
            duration_ms=duration_ms,
        )

    def _transcribe_openai_api(
        self,
        audio_path: str,
        language: Optional[str],
    ) -> TranscriptionResult:
        """Transcribe using OpenAI API."""
        with open(audio_path, "rb") as audio_file:
            # Use timestamps for segment extraction
            response = self._model.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        segments = []
        for seg in getattr(response, 'segments', []):
            segments.append(TranscriptSegment(
                start_ms=int(seg.get('start', 0) * 1000),
                end_ms=int(seg.get('end', 0) * 1000),
                text=seg.get('text', '').strip(),
                confidence=seg.get('avg_logprob', 0.0),
            ))

        duration_ms = int(getattr(response, 'duration', 0) * 1000)

        return TranscriptionResult(
            text=response.text,
            language=getattr(response, 'language', language or 'en'),
            segments=segments,
            confidence_avg=0.0,  # OpenAI doesn't provide overall confidence
            model_name="whisper-1",
            backend=self._backend or "openai-api",
            duration_ms=duration_ms,
        )

    def _transcribe_local_whisper(
        self,
        audio_path: str,
        language: Optional[str],
        word_timestamps: bool,
    ) -> TranscriptionResult:
        """Transcribe using local whisper."""
        result = self._model.transcribe(
            audio_path,
            language=language,
            word_timestamps=word_timestamps,
        )

        segments = []
        for seg in result.get('segments', []):
            segments.append(TranscriptSegment(
                start_ms=int(seg['start'] * 1000),
                end_ms=int(seg['end'] * 1000),
                text=seg['text'].strip(),
                confidence=1.0,  # Local whisper doesn't provide per-segment confidence
            ))

        return TranscriptionResult(
            text=result['text'],
            language=result.get('language', language or 'en'),
            segments=segments,
            confidence_avg=0.0,
            model_name=self.model_name,
            backend=self._backend or "",
            duration_ms=0,  # Would need to calculate from audio
        )


# ============================================================================
# Convenience Function
# ============================================================================

def transcribe_audio(
    audio_path: str,
    model_name: str = "base",
    language: Optional[str] = None,
    device: str = "auto",
) -> TranscriptionResult:
    """
    Convenience function to transcribe audio.

    Supports M4A (AAC), WAV, MP3, and other formats via faster-whisper's
    internal ffmpeg decoder. Per mixtape-audio.md, M4A is the canonical
    archive format - Whisper handles it directly without separate conversion.

    Args:
        audio_path: Path to audio file (local path or storage path)
        model_name: Whisper model size
        language: Language code (auto-detect if None)
        device: Device to use (auto, cpu, cuda)

    Returns:
        TranscriptionResult with transcription data
    """
    # If path is in storage, download to temp file
    if audio_path.startswith("recordings/") or not os.path.exists(audio_path):
        if default_storage.exists(audio_path):
            # Preserve file extension for ffmpeg format detection
            file_ext = Path(audio_path).suffix or ".audio"
            with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
                with default_storage.open(audio_path, 'rb') as src:
                    tmp.write(src.read())
                tmp_path = tmp.name

            try:
                service = WhisperService(model_name=model_name, device=device)
                return service.transcribe(tmp_path, language=language)
            finally:
                os.unlink(tmp_path)
        else:
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Local file
    service = WhisperService(model_name=model_name, device=device)
    return service.transcribe(audio_path, language=language)


def transcribe_recording(
    recording_id: str,
    model_name: str = "base",
    language: Optional[str] = None,
) -> TranscriptionResult:
    """
    Transcribe a Recording by ID.

    Args:
        recording_id: Recording UUID
        model_name: Whisper model size
        language: Language code (auto-detect if None)

    Returns:
        TranscriptionResult with transcription data

    Raises:
        Recording.DoesNotExist: If recording not found
        FileNotFoundError: If audio file not found
    """
    from concord.models import Recording

    recording = Recording.objects.get(id=recording_id)

    # Get audio path
    # source_file_id is a loose UUID reference — resolving it to a path requires a
    # Stackroom REST call, wired at CP3+. Fall through to asset and audio_path for now.
    audio_path = recording.audio_path
    if not audio_path:
        if recording.asset:
            audio_path = recording.asset.file_path
        else:
            raise FileNotFoundError(f"No audio file for recording {recording_id}")

    return transcribe_audio(audio_path, model_name=model_name, language=language)
