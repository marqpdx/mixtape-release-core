from __future__ import annotations

from django.db import transaction

from relations.service import RelationshipService

from .models import Sprig, SprigKind, SprigStatus


class SprigService:
    """
    Entry point for Sprig creation and precommit commit.
    Views and agents must not write Sprig state directly.
    """

    @staticmethod
    @transaction.atomic
    def create_sprig(
        *,
        author,
        sponsor=None,
        body: str = "",
        kind: str = "text",
        audio_url: str = "",
        audio_duration_seconds: int | None = None,
        source: str | None = None,
        metadata: dict | None = None,
    ) -> Sprig:
        sponsor_content_type = None
        sponsor_object_id = None
        if sponsor is not None:
            from django.contrib.contenttypes.models import ContentType
            sponsor_content_type = ContentType.objects.get_for_model(sponsor.__class__)
            sponsor_object_id = sponsor.pk

        return Sprig.objects.create(
            author=author,
            sponsor_content_type=sponsor_content_type,
            sponsor_object_id=sponsor_object_id,
            body=body,
            kind=kind if kind in SprigKind.values else SprigKind.TEXT,
            audio_url=audio_url,
            audio_duration_seconds=audio_duration_seconds,
            transcript_status="pending" if audio_url else None,
            source=source,
            metadata=metadata or {},
            status=SprigStatus.CAPTURED,
        )

    @staticmethod
    @transaction.atomic
    def commit_sprig(
        *,
        sprig: Sprig,
        relationships: list[dict],
        committed_by,
    ) -> Sprig:
        """
        Confirm precommit. Creates Relationship records and marks the Sprig COMMITTED.

        relationships: list of dicts, each with:
          - "target": the related object instance
          - "type_slug": RelationshipType slug (e.g. "contributes-to", "supports")
          - "notes": optional str
        """
        for rel in relationships:
            RelationshipService.create_relationship(
                type_slug=rel["type_slug"],
                source=sprig,
                target=rel["target"],
                created_by=committed_by,
                notes=rel.get("notes", ""),
            )

        sprig.status = SprigStatus.COMMITTED
        sprig.save(update_fields=["status", "updated_at"])
        return sprig

    @staticmethod
    @transaction.atomic
    def archive_sprig(*, sprig: Sprig) -> Sprig:
        sprig.status = SprigStatus.ARCHIVED
        sprig.save(update_fields=["status", "updated_at"])
        return sprig
