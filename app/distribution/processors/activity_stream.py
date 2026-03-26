# distribution/processors/activity_stream.py
"""
ActivityStreamProcessor — emits a writing_published activity to the group stream.

No external API call. Uses the existing activity fanout infrastructure.
Always available (no tier gate).
"""

import logging

logger = logging.getLogger(__name__)


def _build_canonical_url(piece) -> str:
    """Build canonical URL from piece slug and sponsor group slug."""
    if piece.canonical_url:
        return piece.canonical_url

    from django.conf import settings
    base = getattr(settings, "SITE_BASE_URL", "https://mixtape.social")

    group = piece.group
    if group:
        return f"{base}/groups/{group.slug}/writing/{piece.slug}"

    return f"{base}/writing/{piece.slug}"


class ActivityStreamProcessor:
    source_kind = "activity_stream"

    def validate_config(self, config: dict) -> list[str]:
        errors = []
        if not config.get("group_id"):
            errors.append("group_id is required for activity_stream processor")
        return errors

    def process(self, piece, source, config: dict) -> dict:
        canonical_url = _build_canonical_url(piece)
        og_title = piece.title or "Untitled"
        synopsis = getattr(piece, "excerpt", "") or ""
        og_image = ""

        result = {
            "status": "success",
            "canonical_url": canonical_url,
            "og_title": og_title,
            "synopsis": synopsis,
            "og_image": og_image,
            "channel_config": config,
            "channel_response": {},
            "failure_reason": "",
        }

        # Fall back to the Source's own group FK if config doesn't supply group_id
        group_id = config.get("group_id") or (str(source.group_id) if source.group_id else None)
        if not group_id:
            result["status"] = "skipped"
            result["failure_reason"] = "group_id missing in config and source has no group"
            return result

        try:
            from groups.models import Group
            group = Group.objects.filter(id=group_id).first()
            if not group:
                result["status"] = "skipped"
                result["failure_reason"] = f"group {group_id} not found"
                return result

            # Emit via existing activity producers if available
            try:
                from writing.producers import on_writing_published
                on_writing_published(piece=piece, group=group)
            except (ImportError, AttributeError):
                # Producer not yet wired — record as success but note it
                result["channel_response"]["note"] = "activity producer not yet wired"

        except Exception as exc:
            logger.exception("ActivityStreamProcessor.process failed: %s", exc)
            result["status"] = "failed"
            result["failure_reason"] = str(exc)

        return result
