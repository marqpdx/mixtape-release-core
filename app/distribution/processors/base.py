# distribution/processors/base.py
"""
SourceProcessor protocol — the contract every channel processor must satisfy.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class SourceProcessor(Protocol):
    """
    Interface for external distribution channel processors.

    Each processor implements distribution to a single channel kind
    (LinkedIn, ActivityStream, email, etc.).

    Processors must not raise. All errors are captured in the returned dict
    and a ShareRecord with status='failed' is created by the service.
    """
    source_kind: str

    def validate_config(self, config: dict) -> list[str]:
        """
        Validate per-publish channel config.
        Returns a list of human-readable error strings, or [] if valid.
        """
        ...

    def process(
        self,
        piece,           # writing.models.WritingPiece
        source,          # distribution.models.Source
        config: dict,    # per-publish channel config
    ) -> dict:
        """
        Execute the distribution action.

        Returns a dict with keys:
          status:           'success' | 'failed' | 'skipped'
          canonical_url:    str  (captured from piece at call time)
          og_title:         str
          synopsis:         str
          og_image:         str
          channel_config:   dict  (snapshot of config used)
          channel_response: dict  (channel-specific response data)
          failure_reason:   str  (if status != 'success')
        """
        ...
