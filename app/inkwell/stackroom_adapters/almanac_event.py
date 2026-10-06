from __future__ import annotations

from uuid import UUID

from almanac.models import Event
from stackroom_client import get_or_create_group_library, get_or_create_user_library

from .base import BaseStackroomAdapter


class AlmanacEventAdapter(BaseStackroomAdapter):
    adapter_name = "almanac_event"

    def supports(self, obj) -> bool:
        return isinstance(obj, Event)

    def build_text(self, event: Event) -> str:
        parts: list[str] = [event.title]

        if event.description:
            parts.append(event.description)

        if event.location:
            parts.append(f"Location: {event.location}")

        if event.event_format:
            parts.append(f"Format: {event.event_format}")

        # Occurrence timing and notes — notes are the primary home for door codes
        if hasattr(event, "series") and event.series:
            for occ in event.series.occurrences.filter(is_cancelled=False).order_by("start")[:5]:
                occ_parts = [f"Date/Time: {occ.start.strftime('%A, %B %d %Y at %I:%M %p')}"]
                effective_location = occ.location_override or event.location
                if effective_location:
                    occ_parts.append(f"Location: {effective_location}")
                if occ.notes:
                    occ_parts.append(f"Notes: {occ.notes}")
                parts.append("\n".join(occ_parts))

        # Decorator context data (instructions, special info, etc.)
        for assignment in event.decorator_assignments.select_related("decorator").all():
            if assignment.context_data:
                parts.append(f"{assignment.decorator.name}: {assignment.context_data}")

        return "\n\n".join(parts)

    def get_library_id(self, event: Event) -> UUID:
        if (event.sponsor_content_type and
                event.sponsor_content_type.model == "group"):
            group_model = event.sponsor_content_type.model_class()
            group = group_model.objects.get(pk=event.sponsor_object_id)
            return get_or_create_group_library(group)
        return get_or_create_user_library(event.author)

    def get_source_path(self, event: Event) -> str:
        return f"almanac/events/{event.pk}.txt"
