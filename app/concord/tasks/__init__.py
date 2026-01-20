# concord/tasks/__init__.py
"""
Concord Celery tasks for audio processing.
"""

from .transcription import transcribe_recording_task
from .interpretation import interpret_recording_task

__all__ = ['transcribe_recording_task', 'interpret_recording_task']
