# distribution/processors/registry.py
"""
Processor registry. Maps source_kind → SourceProcessor instance.
Import here to register processors.
"""

from .activity_stream import ActivityStreamProcessor
from .linkedin import LinkedInProcessor

PROCESSOR_REGISTRY: dict = {
    "activity_stream": ActivityStreamProcessor(),
    "linkedin": LinkedInProcessor(),
}


def get_processor(source_kind: str):
    """Return the processor for the given source_kind, or None if not found."""
    return PROCESSOR_REGISTRY.get(source_kind)
