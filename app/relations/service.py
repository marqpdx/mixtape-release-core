from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .models import Relationship, RelationshipAnnotation, RelationshipType


class RelationshipService:
    """
    Single entry point for all Relationship creation, archival, and traversal.
    Invariant: no direct ORM relationship writes from views, serializers, or agents.
    """

    # -------------------------------------------------------------------------
    # Writes
    # -------------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def create_relationship(
        *,
        type_slug: str,
        source,
        target,
        created_by,
        position: int | None = None,
        weight: float | None = None,
        visibility: str = Relationship.VISIBILITY_PUBLIC,
        notes: str = "",
        metadata: dict | None = None,
    ) -> Relationship:
        rel_type = RelationshipType.objects.get(slug=type_slug)
        source_ct = ContentType.objects.get_for_model(source.__class__)
        target_ct = ContentType.objects.get_for_model(target.__class__)

        relationship = Relationship.objects.create(
            relationship_type=rel_type,
            source_content_type=source_ct,
            source_object_id=source.pk,
            target_content_type=target_ct,
            target_object_id=target.pk,
            created_by=created_by,
            position=position,
            weight=weight,
            visibility=visibility,
            notes=notes,
            metadata=metadata or {},
            status=Relationship.STATUS_ACTIVE,
        )

        from . import producers
        producers.on_relationship_created(relationship)

        return relationship

    @staticmethod
    @transaction.atomic
    def archive_relationship(*, relationship_id, archived_by=None) -> Relationship:
        relationship = Relationship.objects.select_for_update().get(pk=relationship_id)
        relationship.status = Relationship.STATUS_ARCHIVED
        relationship.save(update_fields=["status", "updated_at"])

        from . import producers
        producers.on_relationship_archived(relationship)

        return relationship

    @staticmethod
    @transaction.atomic
    def acknowledge_relationship(*, relationship_id, acknowledged_by=None) -> "Relationship":
        from django.utils import timezone
        relationship = Relationship.objects.select_for_update().get(pk=relationship_id)
        if relationship.lifecycle in (Relationship.LIFECYCLE_ACKNOWLEDGED, Relationship.LIFECYCLE_MUTUAL):
            return relationship
        relationship.lifecycle = Relationship.LIFECYCLE_ACKNOWLEDGED
        meta = relationship.metadata or {}
        meta["acknowledged_at"] = timezone.now().isoformat()
        if acknowledged_by:
            meta["acknowledged_by"] = str(acknowledged_by.pk)
        relationship.metadata = meta
        relationship.save(update_fields=["lifecycle", "metadata", "updated_at"])
        return relationship

    @staticmethod
    @transaction.atomic
    def annotate_relationship(
        *, relationship_id, body: str = "", anchor_text: str = ""
    ) -> RelationshipAnnotation:
        relationship = Relationship.objects.get(pk=relationship_id)
        annotation, _ = RelationshipAnnotation.objects.update_or_create(
            relationship=relationship,
            defaults={"body": body, "anchor_text": anchor_text},
        )
        return annotation

    # -------------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------------

    @staticmethod
    def get_outgoing(obj, *, type_slug: str | None = None, domain: str | None = None, status: str = Relationship.STATUS_ACTIVE):
        ct = ContentType.objects.get_for_model(obj.__class__)
        qs = Relationship.objects.filter(
            source_content_type=ct,
            source_object_id=obj.pk,
            status=status,
        ).select_related("source_content_type", "target_content_type", "relationship_type")
        if type_slug:
            qs = qs.filter(relationship_type__slug=type_slug)
        if domain:
            qs = qs.filter(relationship_type__domain=domain)
        return qs

    @staticmethod
    def get_incoming(obj, *, type_slug: str | None = None, domain: str | None = None, status: str = Relationship.STATUS_ACTIVE):
        ct = ContentType.objects.get_for_model(obj.__class__)
        qs = Relationship.objects.filter(
            target_content_type=ct,
            target_object_id=obj.pk,
            status=status,
        ).select_related("source_content_type", "target_content_type", "relationship_type")
        if type_slug:
            qs = qs.filter(relationship_type__slug=type_slug)
        if domain:
            qs = qs.filter(relationship_type__domain=domain)
        return qs

    @staticmethod
    def prefetch_endpoints(relationships):
        """
        GFK prefetch helper. select_related() cannot traverse GFK — always use this
        when resolving source/target objects from a Relationship queryset.
        Returns dict keyed by (content_type_id, object_id) → object.
        """
        ct_ids = set()
        for r in relationships:
            ct_ids.add(r.source_content_type_id)
            ct_ids.add(r.target_content_type_id)

        ct_map = {ct.pk: ct for ct in ContentType.objects.filter(pk__in=ct_ids)}
        endpoint_map: dict = {}

        for ct_id in ct_ids:
            if ct_id not in ct_map:
                continue
            ct = ct_map[ct_id]
            model_class = ct.model_class()
            if model_class is None:
                continue
            source_ids = {
                r.source_object_id for r in relationships if r.source_content_type_id == ct_id
            }
            target_ids = {
                r.target_object_id for r in relationships if r.target_content_type_id == ct_id
            }
            all_ids = source_ids | target_ids
            for obj in model_class.objects.filter(pk__in=all_ids):
                endpoint_map[(ct_id, str(obj.pk))] = obj

        return endpoint_map

    # -------------------------------------------------------------------------
    # Tree traversal (Living Book)
    # -------------------------------------------------------------------------

    @staticmethod
    def get_tree(root_obj, *, type_slug: str = "contains", max_depth: int = 4) -> list:
        """
        DFS traversal of positioned relationships from root_obj.
        Returns an ordered list of dicts: [{obj, depth, position, relationship}, ...].
        Depth guardrail: stops at max_depth (ADR invariant — default 4 for Living Book).
        """
        root_ct = ContentType.objects.get_for_model(root_obj.__class__)

        def _walk(ct_id, obj_id, depth, visited):
            if depth > max_depth or (ct_id, obj_id) in visited:
                return []
            visited = visited | {(ct_id, obj_id)}

            edges = (
                Relationship.objects.filter(
                    source_content_type_id=ct_id,
                    source_object_id=obj_id,
                    relationship_type__slug=type_slug,
                    status=Relationship.STATUS_ACTIVE,
                )
                .select_related("target_content_type", "relationship_type")
                .order_by("position", "created_at")
            )

            nodes = []
            for edge in edges:
                target_ct = edge.target_content_type
                target_model = target_ct.model_class()
                if target_model is None:
                    continue
                try:
                    target_obj = target_model.objects.get(pk=edge.target_object_id)
                except target_model.DoesNotExist:
                    continue
                nodes.append({
                    "obj": target_obj,
                    "depth": depth,
                    "position": edge.position,
                    "relationship": edge,
                })
                nodes.extend(_walk(target_ct.pk, edge.target_object_id, depth + 1, visited))

            return nodes

        return _walk(root_ct.pk, root_obj.pk, 1, set())
