# groups/page_slots.py
#
# Template slot registry for the Crossroads Page (DB-0002).
# Phase 2: Group DB fields only.
# Phase 3 adds Catalyst Codex file bindings.
# Phase 4 adds ad hoc PageComponent records.
#
# Each slot entry:
#   type    — "string" | "url" | "integer"
#   source  — "group_field" (Phase 2 only)
#   field   — attribute name on the Group instance

PAGE_SLOTS: dict[str, dict] = {
    "title": {
        "type": "string",
        "source": "group_field",
        "field": "title",
    },
    "quick_intro": {
        "type": "string",
        "source": "group_field",
        "field": "quick_intro",
    },
    "description": {
        "type": "string",
        "source": "group_field",
        "field": "description",
    },
    "group_type": {
        "type": "string",
        "source": "group_field",
        "field": "group_type",
    },
    "member_count": {
        "type": "integer",
        "source": "group_field",
        "field": "member_count",
    },
    "profile_image_url": {
        "type": "url",
        "source": "group_field",
        "field": "profile_image_url",
    },
    "background_image_url": {
        "type": "url",
        "source": "group_field",
        "field": "background_image_url",
    },
}


def render_group_slots(group) -> dict:
    """
    Populate slot values from a Group instance.

    Returns a dict keyed by slot name. Values are the current live values
    from the Group model; they are not sanitized here — sanitization happens
    at the rendering layer (React JSX / server-side).
    """
    result: dict = {}
    for slot_name, config in PAGE_SLOTS.items():
        if config["source"] == "group_field":
            value = getattr(group, config["field"], None)
            result[slot_name] = value
    return result
