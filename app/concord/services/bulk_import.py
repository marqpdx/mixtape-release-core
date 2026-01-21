# concord/services/bulk_import.py
# ============================================================================
# Bulk Session Import Service
#
# Handles bulk upload of audio/video files via zip:
# - Extract zip to temp directory
# - Parse folder structure (each folder = one RecordingSession)
# - Find audio/video files in each folder
# - Convert MKV/video to WAV for Whisper processing
# - Create RecordingSession and Recording objects
# - Upload processed files to S3
# - Auto-create Library for the batch
# - Optionally queue transcription tasks
# ============================================================================

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from concord.models import (
    Recording,
    RecordingSession,
    RecordingStatus,
    SessionStatus,
)


# ============================================================================
# Signals
# ============================================================================

# Signal emitted when a bulk import batch is created
# Provides: batch_id, library, sessions, group, user
bulk_import_completed = Signal()


# ============================================================================
# Constants
# ============================================================================

MAX_ZIP_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB per file
MAX_SESSIONS_PER_UPLOAD = 50
MAX_RECORDINGS_PER_SESSION = 20

# Audio formats that can be processed directly
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.webm', '.flac'}

# Video formats that need audio extraction
VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.webm'}

# All supported formats
SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ImportedRecording:
    """Represents an imported recording before DB creation."""
    original_path: Path
    processed_path: Optional[Path] = None  # WAV path after conversion (temp, for Whisper)
    archive_path: Optional[Path] = None    # M4A path for canonical storage
    filename: str = ""
    segment_index: int = 0
    duration_ms: Optional[int] = None
    content_type: str = ""
    size_bytes: int = 0
    needs_conversion: bool = False


@dataclass
class ImportedSession:
    """Represents an imported session (folder) before DB creation."""
    folder_name: str
    folder_path: Path
    recordings: list[ImportedRecording] = field(default_factory=list)


@dataclass
class BulkImportResult:
    """Result of a bulk import operation."""
    success: bool
    batch_id: str
    library_id: Optional[str] = None
    sessions_created: int = 0
    recordings_created: int = 0
    transcription_tasks_queued: int = 0
    sessions: list = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ============================================================================
# BulkImportService
# ============================================================================

class BulkImportService:
    """
    Service for bulk importing audio/video files from a zip archive.

    Each top-level folder in the zip becomes a RecordingSession.
    Each audio/video file in a folder becomes a Recording.
    MKV and other video files are converted to WAV for Whisper processing.
    """

    def __init__(
        self,
        group,
        user,
        auto_transcribe: bool = True,
        whisper_model: str = 'base',
    ):
        self.group = group
        self.user = user
        self.auto_transcribe = auto_transcribe
        self.whisper_model = whisper_model
        self.batch_id = str(uuid.uuid4())
        self.temp_dir: Optional[Path] = None
        self.uploaded_paths: list[str] = []  # Track for cleanup on failure

    def import_files(
        self,
        files: list,
        paths: list[str],
        session_title: str = "",
    ) -> BulkImportResult:
        """
        Import sessions from multiple files with their relative paths.

        Path interpretation:
        - Single file at root (e.g., "recording.mp3") → standalone Recording, no Session
        - Multiple files at root → one Session containing all files
        - Files in subdirectories → each top-level directory becomes a Session

        Examples:
        - ["file1.mp3", "file2.mp3"] → 1 Session with 2 Recordings
        - ["lectures/part1.mp3", "lectures/part2.mp3"] → 1 Session "lectures"
        - ["lecture1/a.mp3", "lecture2/b.mp3"] → 2 Sessions

        Args:
            files: List of uploaded file objects
            paths: List of relative paths (from webkitRelativePath)
            session_title: Optional override title for single-session imports

        Returns:
            BulkImportResult with status and created objects
        """
        result = BulkImportResult(
            success=False,
            batch_id=self.batch_id,
        )

        if len(files) != len(paths):
            result.errors.append(
                f"Mismatch: {len(files)} files but {len(paths)} paths"
            )
            return result

        if not files:
            result.errors.append("No files provided")
            return result

        try:
            # Create temp directory for processing
            self.temp_dir = Path(tempfile.mkdtemp(prefix='concord_multi_'))

            # Group files by their top-level directory
            grouped = self._group_files_by_directory(files, paths, result)

            if not grouped:
                if not result.errors:
                    result.errors.append("No valid audio/video files found")
                return result

            # Convert grouped files to ImportedSession objects
            sessions = self._create_sessions_from_groups(grouped, session_title, result)

            if not sessions:
                return result

            # Process video files (convert to WAV)
            self._process_video_files(sessions, result)

            # Import to database
            with transaction.atomic():
                db_sessions, standalone_recordings = self._create_db_objects_multi(
                    sessions, result
                )

                # Create Library for the batch (if we have sessions)
                library = None
                if db_sessions:
                    library_title = session_title or f"Import {timezone.now().strftime('%Y-%m-%d %H:%M')}"
                    library = self._create_batch_library(
                        library_title,
                        db_sessions,
                        result
                    )
                    if library:
                        result.library_id = str(library.id)

                # Queue transcription tasks if requested
                if self.auto_transcribe:
                    self._queue_transcription_tasks(db_sessions, result)
                    # Also queue for standalone recordings
                    for recording in standalone_recordings:
                        from concord.tasks.transcription import transcribe_recording_task
                        transcribe_recording_task.delay(
                            recording_id=str(recording.id),
                            model_name=self.whisper_model,
                        )
                        result.transcription_tasks_queued += 1

                result.sessions = [
                    {
                        'id': str(s.id),
                        'title': s.title,
                        'recording_count': s.segments.count(),
                    }
                    for s in db_sessions
                ]

            result.success = True

            # Emit signal
            if db_sessions:
                bulk_import_completed.send(
                    sender=self.__class__,
                    batch_id=self.batch_id,
                    library=library,
                    sessions=db_sessions,
                    group=self.group,
                    user=self.user,
                )

        except Exception as e:
            result.errors.append(f"Import failed: {str(e)}")
            self._cleanup_uploads()

        finally:
            self._cleanup_temp()

        return result

    def _group_files_by_directory(
        self,
        files: list,
        paths: list[str],
        result: BulkImportResult
    ) -> dict[str, list[tuple]]:
        """
        Group files by their top-level directory.

        Returns dict: { "directory_name": [(file, path, filename), ...] }
        Special key "" (empty string) for root-level files.
        """
        grouped: dict[str, list[tuple]] = {}

        for file, path in zip(files, paths):
            # Normalize path
            path = path.replace('\\', '/')

            # Check if supported file type
            ext = Path(path).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                result.warnings.append(f"Skipping unsupported file: {path}")
                continue

            # Check file size
            if file.size > MAX_FILE_SIZE:
                result.warnings.append(
                    f"Skipping {path}: exceeds {MAX_FILE_SIZE / (1024*1024):.0f}MB limit"
                )
                continue

            # Determine top-level directory
            parts = path.split('/')
            if len(parts) == 1:
                # Root level file
                dir_key = ""
            else:
                # File in subdirectory - use first directory as session name
                dir_key = parts[0]

            if dir_key not in grouped:
                grouped[dir_key] = []

            grouped[dir_key].append((file, path, parts[-1]))

        return grouped

    def _create_sessions_from_groups(
        self,
        grouped: dict[str, list[tuple]],
        session_title: str,
        result: BulkImportResult
    ) -> list[ImportedSession]:
        """Convert grouped files into ImportedSession objects."""
        sessions = []

        # Check limits
        if len(grouped) > MAX_SESSIONS_PER_UPLOAD:
            result.errors.append(
                f"Too many sessions: {len(grouped)}. Maximum is {MAX_SESSIONS_PER_UPLOAD}."
            )
            return []

        for dir_key, file_list in grouped.items():
            if len(file_list) > MAX_RECORDINGS_PER_SESSION:
                result.warnings.append(
                    f"Directory '{dir_key or 'root'}' has {len(file_list)} files, "
                    f"limiting to {MAX_RECORDINGS_PER_SESSION}"
                )
                file_list = file_list[:MAX_RECORDINGS_PER_SESSION]

            # Determine session name
            if dir_key:
                folder_name = dir_key
            elif session_title:
                folder_name = session_title
            elif len(file_list) == 1:
                # Single file at root - will be standalone recording
                folder_name = ""
            else:
                folder_name = f"Upload {timezone.now().strftime('%Y-%m-%d %H:%M')}"

            session = ImportedSession(
                folder_name=folder_name,
                folder_path=self.temp_dir / (dir_key or "root"),
            )

            # Save files to temp and create ImportedRecording objects
            for idx, (file, path, filename) in enumerate(sorted(file_list, key=lambda x: x[1])):
                temp_path = self._save_to_temp(file, path)
                if temp_path:
                    ext = temp_path.suffix.lower()
                    recording = ImportedRecording(
                        original_path=temp_path,
                        filename=filename,
                        segment_index=self._parse_segment_index(filename, idx),
                        content_type=self._get_content_type(ext),
                        size_bytes=temp_path.stat().st_size,
                        needs_conversion=ext in VIDEO_EXTENSIONS,
                    )
                    session.recordings.append(recording)

            if session.recordings:
                sessions.append(session)

        return sessions

    def _save_to_temp(self, file, path: str) -> Optional[Path]:
        """Save uploaded file to temp directory, preserving structure."""
        try:
            # Create subdirectories if needed
            rel_path = Path(path.replace('\\', '/'))
            temp_path = self.temp_dir / rel_path
            temp_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            with open(temp_path, 'wb') as f:
                for chunk in file.chunks():
                    f.write(chunk)

            return temp_path
        except Exception as e:
            return None

    def _get_content_type(self, ext: str) -> str:
        """Get MIME type for file extension."""
        content_type_map = {
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.m4a': 'audio/mp4',
            '.aac': 'audio/aac',
            '.ogg': 'audio/ogg',
            '.webm': 'audio/webm',
            '.flac': 'audio/flac',
            '.mkv': 'video/x-matroska',
            '.mp4': 'video/mp4',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
        }
        return content_type_map.get(ext, 'application/octet-stream')

    def _create_db_objects_multi(
        self,
        sessions: list[ImportedSession],
        result: BulkImportResult
    ) -> tuple[list[RecordingSession], list[Recording]]:
        """
        Create DB objects, handling both sessions and standalone recordings.

        Returns (db_sessions, standalone_recordings)
        """
        db_sessions = []
        standalone_recordings = []
        content_type = ContentType.objects.get_for_model(type(self.group))

        for imported_session in sessions:
            # Check if this is a standalone recording (single file, no folder name)
            is_standalone = (
                not imported_session.folder_name and
                len(imported_session.recordings) == 1
            )

            if is_standalone:
                # Create standalone Recording without Session
                imported_rec = imported_session.recordings[0]
                # Priority: archive_path (M4A) > original_path (for non-video files)
                if imported_rec.archive_path:
                    file_to_upload = imported_rec.archive_path
                else:
                    file_to_upload = imported_rec.original_path

                storage_path = self._upload_to_storage_standalone(
                    file_to_upload,
                    imported_rec.filename,
                )

                if storage_path:
                    self.uploaded_paths.append(storage_path)

                    recording = Recording.objects.create(
                        sponsor_content_type=content_type,
                        sponsor_object_id=self.group.id,
                        title=imported_rec.filename,
                        audio_path=storage_path,
                        audio_content_type=imported_rec.content_type,
                        audio_size_bytes=file_to_upload.stat().st_size,
                        status=RecordingStatus.UPLOADED,
                        submitted_by=self.user,
                    )
                    standalone_recordings.append(recording)
                    result.recordings_created += 1
            else:
                # Create RecordingSession with Recordings
                db_session = RecordingSession.objects.create(
                    sponsor_content_type=content_type,
                    sponsor_object_id=self.group.id,
                    title=imported_session.folder_name,
                    status=SessionStatus.COMPLETED,
                    submitted_by=self.user,
                )
                db_sessions.append(db_session)
                result.sessions_created += 1

                for imported_rec in imported_session.recordings:
                    # Priority: archive_path (M4A) > original_path (for non-video files)
                    if imported_rec.archive_path:
                        file_to_upload = imported_rec.archive_path
                    else:
                        file_to_upload = imported_rec.original_path

                    storage_path = self._upload_to_storage(
                        file_to_upload,
                        db_session,
                        imported_rec.filename,
                    )

                    if storage_path:
                        self.uploaded_paths.append(storage_path)

                        Recording.objects.create(
                            sponsor_content_type=content_type,
                            sponsor_object_id=self.group.id,
                            session=db_session,
                            segment_index=imported_rec.segment_index,
                            title=imported_rec.filename,
                            audio_path=storage_path,
                            audio_content_type=imported_rec.content_type,
                            audio_size_bytes=file_to_upload.stat().st_size,
                            status=RecordingStatus.UPLOADED,
                            submitted_by=self.user,
                        )
                        result.recordings_created += 1

        return db_sessions, standalone_recordings

    def _upload_to_storage_standalone(
        self,
        file_path: Path,
        original_filename: str,
    ) -> Optional[str]:
        """Upload standalone recording file to S3/storage."""
        recording_id = uuid.uuid4()
        storage_key = (
            f"recordings/group/{self.group.id}/"
            f"{recording_id}/{original_filename}"
        )

        # Use the actual file extension (M4A for converted video files)
        actual_ext = file_path.suffix.lower()
        original_ext = Path(original_filename).suffix.lower()
        if actual_ext != original_ext:
            storage_key = storage_key.rsplit('.', 1)[0] + actual_ext

        with open(file_path, 'rb') as f:
            saved_path = default_storage.save(storage_key, ContentFile(f.read()))

        return saved_path

    def import_zip(self, zip_file, zip_filename: str = "upload.zip") -> BulkImportResult:
        """
        Import sessions from a zip file.

        Args:
            zip_file: File-like object containing the zip
            zip_filename: Original filename for Library naming

        Returns:
            BulkImportResult with status and created objects
        """
        result = BulkImportResult(
            success=False,
            batch_id=self.batch_id,
        )

        try:
            # Validate zip size
            zip_file.seek(0, 2)  # Seek to end
            zip_size = zip_file.tell()
            zip_file.seek(0)  # Reset

            if zip_size > MAX_ZIP_SIZE:
                result.errors.append(
                    f"Zip file too large: {zip_size / (1024*1024*1024):.2f}GB. "
                    f"Maximum is {MAX_ZIP_SIZE / (1024*1024*1024):.0f}GB."
                )
                return result

            # Create temp directory
            self.temp_dir = Path(tempfile.mkdtemp(prefix='concord_bulk_'))

            # Extract zip
            sessions = self._extract_and_parse_zip(zip_file, result)
            if not sessions:
                if not result.errors:
                    result.errors.append("No valid sessions found in zip file")
                return result

            # Validate limits
            if len(sessions) > MAX_SESSIONS_PER_UPLOAD:
                result.errors.append(
                    f"Too many sessions: {len(sessions)}. "
                    f"Maximum is {MAX_SESSIONS_PER_UPLOAD}."
                )
                return result

            # Process video files (convert to WAV)
            self._process_video_files(sessions, result)

            # Import to database
            with transaction.atomic():
                db_sessions = self._create_db_objects(sessions, result)

                # Create Library for the batch
                library = self._create_batch_library(
                    zip_filename,
                    db_sessions,
                    result
                )

                if library:
                    result.library_id = str(library.id)

                # Queue transcription tasks if requested
                if self.auto_transcribe:
                    self._queue_transcription_tasks(db_sessions, result)

                result.sessions = [
                    {
                        'id': str(s.id),
                        'title': s.title,
                        'recording_count': s.segments.count(),
                    }
                    for s in db_sessions
                ]

            result.success = True

            # Emit signal for any additional processing
            bulk_import_completed.send(
                sender=self.__class__,
                batch_id=self.batch_id,
                library=library,
                sessions=db_sessions,
                group=self.group,
                user=self.user,
            )

        except Exception as e:
            result.errors.append(f"Import failed: {str(e)}")
            # Cleanup uploaded files on failure
            self._cleanup_uploads()

        finally:
            # Always cleanup temp directory
            self._cleanup_temp()

        return result

    def _extract_and_parse_zip(
        self,
        zip_file,
        result: BulkImportResult
    ) -> list[ImportedSession]:
        """Extract zip and parse folder structure."""
        sessions = []

        try:
            with zipfile.ZipFile(zip_file, 'r') as zf:
                # Extract all
                zf.extractall(self.temp_dir)

                # Find top-level folders (each becomes a session)
                for item in self.temp_dir.iterdir():
                    if item.is_dir() and not item.name.startswith('.'):
                        session = self._parse_folder(item, result)
                        if session and session.recordings:
                            sessions.append(session)
                        elif session:
                            result.warnings.append(
                                f"Folder '{item.name}' has no valid audio/video files"
                            )
                    elif item.is_file() and self._is_supported_file(item):
                        # Handle files at root level - create session from filename
                        session = ImportedSession(
                            folder_name=item.stem,
                            folder_path=self.temp_dir,
                        )
                        recording = self._parse_audio_file(item, 0)
                        if recording:
                            session.recordings.append(recording)
                            sessions.append(session)

        except zipfile.BadZipFile:
            result.errors.append("Invalid zip file")

        return sessions

    def _parse_folder(
        self,
        folder_path: Path,
        result: BulkImportResult
    ) -> Optional[ImportedSession]:
        """Parse a folder into an ImportedSession."""
        session = ImportedSession(
            folder_name=folder_path.name,
            folder_path=folder_path,
        )

        # Find audio/video files
        audio_files = sorted([
            f for f in folder_path.iterdir()
            if f.is_file() and self._is_supported_file(f)
        ])

        if len(audio_files) > MAX_RECORDINGS_PER_SESSION:
            result.warnings.append(
                f"Folder '{folder_path.name}' has {len(audio_files)} files, "
                f"limiting to {MAX_RECORDINGS_PER_SESSION}"
            )
            audio_files = audio_files[:MAX_RECORDINGS_PER_SESSION]

        for idx, audio_file in enumerate(audio_files):
            recording = self._parse_audio_file(audio_file, idx)
            if recording:
                # Check file size
                if recording.size_bytes > MAX_FILE_SIZE:
                    result.warnings.append(
                        f"File '{audio_file.name}' exceeds {MAX_FILE_SIZE / (1024*1024):.0f}MB limit, skipping"
                    )
                    continue
                session.recordings.append(recording)

        return session

    def _parse_audio_file(
        self,
        file_path: Path,
        default_index: int
    ) -> Optional[ImportedRecording]:
        """Parse an audio/video file into an ImportedRecording."""
        if not file_path.exists():
            return None

        # Determine content type and if conversion needed
        ext = file_path.suffix.lower()
        needs_conversion = ext in VIDEO_EXTENSIONS

        content_type_map = {
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.m4a': 'audio/mp4',
            '.aac': 'audio/aac',
            '.ogg': 'audio/ogg',
            '.webm': 'audio/webm',
            '.flac': 'audio/flac',
            '.mkv': 'video/x-matroska',
            '.mp4': 'video/mp4',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
        }

        return ImportedRecording(
            original_path=file_path,
            filename=file_path.name,
            segment_index=self._parse_segment_index(file_path.name, default_index),
            content_type=content_type_map.get(ext, 'application/octet-stream'),
            size_bytes=file_path.stat().st_size,
            needs_conversion=needs_conversion,
        )

    def _parse_segment_index(self, filename: str, default: int) -> int:
        """
        Parse segment index from filename.

        Patterns:
        - part-01.mp3 → 0
        - segment_1.wav → 0
        - 01.mp3 → 0
        - recording-part-03.mkv → 2
        """
        patterns = [
            r'part[_-]?(\d+)',
            r'segment[_-]?(\d+)',
            r'^(\d+)\.',
            r'[_-](\d+)\.[^.]+$',
        ]

        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return int(match.group(1)) - 1  # Convert to 0-based

        return default

    def _is_supported_file(self, file_path: Path) -> bool:
        """Check if file has a supported extension."""
        return file_path.suffix.lower() in SUPPORTED_EXTENSIONS

    def _process_video_files(
        self,
        sessions: list[ImportedSession],
        result: BulkImportResult
    ):
        """
        Convert video files (MKV, etc.) to both WAV and M4A.

        Per mixtape-audio.md:
        - WAV: temp working format for Whisper ASR (regenerable)
        - M4A: canonical archive format for long-term storage
        - MKV: ephemeral capture artifact (deleted after successful ingestion)

        Pipeline: MKV → WAV (temp) + M4A (canonical) → delete MKV after success
        """
        for session in sessions:
            for recording in session.recordings:
                if recording.needs_conversion:
                    # Create WAV for Whisper processing (temp)
                    wav_path = self._convert_to_wav(recording.original_path, result)
                    if wav_path:
                        recording.processed_path = wav_path
                    else:
                        result.warnings.append(
                            f"Failed to create WAV for '{recording.filename}', "
                            "Whisper may fail on this file"
                        )

                    # Create M4A for canonical storage
                    m4a_path = self._convert_to_m4a(recording.original_path, result)
                    if m4a_path:
                        recording.archive_path = m4a_path
                        recording.content_type = 'audio/mp4'  # MIME type for M4A
                    else:
                        # Fall back to WAV if M4A conversion fails
                        if wav_path:
                            result.warnings.append(
                                f"M4A conversion failed for '{recording.filename}', "
                                "storing as WAV instead"
                            )
                            recording.archive_path = wav_path
                            recording.content_type = 'audio/wav'
                        else:
                            result.warnings.append(
                                f"All conversions failed for '{recording.filename}', "
                                "will use original file"
                            )

    def _convert_to_wav(
        self,
        input_path: Path,
        result: BulkImportResult
    ) -> Optional[Path]:
        """
        Convert video/audio file to WAV using ffmpeg.

        Pipeline: SourceFile (MKV) → extract audio → normalize to WAV
        """
        output_path = input_path.with_suffix('.wav')

        try:
            # ffmpeg command:
            # -i input: input file
            # -vn: no video
            # -acodec pcm_s16le: 16-bit PCM (Whisper compatible)
            # -ar 16000: 16kHz sample rate (Whisper optimal)
            # -ac 1: mono (Whisper works best with mono)
            cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-vn',  # No video
                '-acodec', 'pcm_s16le',  # 16-bit PCM
                '-ar', '16000',  # 16kHz
                '-ac', '1',  # Mono
                '-y',  # Overwrite
                str(output_path),
            ]

            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=300,  # 5 minute timeout per file
            )

            return output_path

        except subprocess.CalledProcessError as e:
            result.warnings.append(
                f"ffmpeg conversion failed for '{input_path.name}': {e.stderr.decode()[:200]}"
            )
        except subprocess.TimeoutExpired:
            result.warnings.append(
                f"ffmpeg conversion timed out for '{input_path.name}'"
            )
        except FileNotFoundError:
            result.errors.append(
                "ffmpeg not found. Install ffmpeg for video conversion support."
            )

        return None

    def _convert_to_m4a(
        self,
        input_path: Path,
        result: BulkImportResult
    ) -> Optional[Path]:
        """
        Convert video/audio file to M4A (AAC) for canonical storage.

        Per mixtape-audio.md:
        - M4A/AAC is the canonical archive format
        - Compact long-term storage
        - Canonical audio is stored as M4A, not WAV
        """
        output_path = input_path.with_suffix('.m4a')

        try:
            # ffmpeg command for M4A/AAC:
            # -i input: input file
            # -vn: no video
            # -c:a aac: AAC audio codec
            # -b:a 128k: 128kbps bitrate (good quality for speech)
            cmd = [
                'ffmpeg',
                '-i', str(input_path),
                '-vn',  # No video
                '-c:a', 'aac',  # AAC codec
                '-b:a', '128k',  # 128kbps bitrate
                '-y',  # Overwrite
                str(output_path),
            ]

            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=300,  # 5 minute timeout per file
            )

            return output_path

        except subprocess.CalledProcessError as e:
            result.warnings.append(
                f"ffmpeg M4A conversion failed for '{input_path.name}': {e.stderr.decode()[:200]}"
            )
        except subprocess.TimeoutExpired:
            result.warnings.append(
                f"ffmpeg M4A conversion timed out for '{input_path.name}'"
            )
        except FileNotFoundError:
            result.errors.append(
                "ffmpeg not found. Install ffmpeg for video conversion support."
            )

        return None

    def _create_db_objects(
        self,
        sessions: list[ImportedSession],
        result: BulkImportResult
    ) -> list[RecordingSession]:
        """Create RecordingSession and Recording objects in database."""
        db_sessions = []
        content_type = ContentType.objects.get_for_model(type(self.group))

        for imported_session in sessions:
            # Create RecordingSession
            db_session = RecordingSession.objects.create(
                sponsor_content_type=content_type,
                sponsor_object_id=self.group.id,
                title=imported_session.folder_name,
                status=SessionStatus.COMPLETED,
                submitted_by=self.user,
            )
            db_sessions.append(db_session)
            result.sessions_created += 1

            # Create Recordings
            for imported_rec in imported_session.recordings:
                # Determine which file to upload as canonical storage
                # Priority: archive_path (M4A) > original_path (for non-video files)
                # Note: processed_path (WAV) is temp-only for Whisper, not stored
                if imported_rec.archive_path:
                    file_to_upload = imported_rec.archive_path
                else:
                    # Non-video files (mp3, m4a, etc.) use original
                    file_to_upload = imported_rec.original_path

                storage_path = self._upload_to_storage(
                    file_to_upload,
                    db_session,
                    imported_rec.filename,
                )

                if storage_path:
                    self.uploaded_paths.append(storage_path)

                    # Create Recording
                    Recording.objects.create(
                        sponsor_content_type=content_type,
                        sponsor_object_id=self.group.id,
                        session=db_session,
                        segment_index=imported_rec.segment_index,
                        title=imported_rec.filename,
                        audio_path=storage_path,
                        audio_content_type=imported_rec.content_type,
                        audio_size_bytes=file_to_upload.stat().st_size,
                        status=RecordingStatus.UPLOADED,
                        submitted_by=self.user,
                    )
                    result.recordings_created += 1

        return db_sessions

    def _upload_to_storage(
        self,
        file_path: Path,
        session: RecordingSession,
        original_filename: str,
    ) -> Optional[str]:
        """Upload file to S3/storage."""
        storage_key = (
            f"recordings/group/{self.group.id}/"
            f"sessions/{session.id}/{original_filename}"
        )

        # Use the actual file extension (M4A for converted video files)
        actual_ext = file_path.suffix.lower()
        original_ext = Path(original_filename).suffix.lower()
        if actual_ext != original_ext:
            storage_key = storage_key.rsplit('.', 1)[0] + actual_ext

        with open(file_path, 'rb') as f:
            saved_path = default_storage.save(storage_key, ContentFile(f.read()))

        return saved_path

    def _create_batch_library(
        self,
        zip_filename: str,
        sessions: list[RecordingSession],
        result: BulkImportResult,
    ):
        """Create a Library for this import batch."""
        from django.contrib.contenttypes.models import ContentType
        from stackroom.models.ir import Library, LibraryItem

        # Generate library title from zip filename
        library_title = Path(zip_filename).stem
        if not library_title or library_title == 'upload':
            library_title = f"Import {timezone.now().strftime('%Y-%m-%d %H:%M')}"

        content_type = ContentType.objects.get_for_model(type(self.group))
        session_content_type = ContentType.objects.get_for_model(RecordingSession)

        # Create Library
        library = Library.objects.create(
            sponsor_content_type=content_type,
            sponsor_object_id=self.group.id,
            title=library_title,
            summary=f"Bulk import of {len(sessions)} recording sessions",
            submitted_by=self.user,
        )

        # Add each session as a LibraryItem
        for idx, session in enumerate(sessions):
            LibraryItem.objects.create(
                library=library,
                content_type=session_content_type,
                content_object_id=session.id,
                order_index=idx,
            )

        return library

    def _queue_transcription_tasks(
        self,
        sessions: list[RecordingSession],
        result: BulkImportResult
    ):
        """Queue transcription tasks for all recordings."""
        from concord.tasks.transcription import transcribe_recording_task

        for session in sessions:
            for recording in session.segments.all():
                transcribe_recording_task.delay(
                    recording_id=str(recording.id),
                    model_name=self.whisper_model,
                )
                result.transcription_tasks_queued += 1

    def _cleanup_uploads(self):
        """Cleanup uploaded files on failure."""
        for path in self.uploaded_paths:
            try:
                default_storage.delete(path)
            except Exception:
                pass

    def _cleanup_temp(self):
        """Cleanup temporary directory."""
        if self.temp_dir and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
            except Exception:
                pass
