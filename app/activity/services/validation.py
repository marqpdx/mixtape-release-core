# activity/services/validation.py

def validate_audience_spec(audience_spec: dict) -> None:
    """
    Validate audience specification payloads at creation time.
    Raises ValueError on invalid specs.
    """
    if not isinstance(audience_spec, dict):
        raise ValueError("audience must be a dict")

    audience_type = audience_spec.get("type")
    if not audience_type:
        raise ValueError("audience.type is required")

    if audience_type == "users":
        ids = audience_spec.get("ids")
        if not isinstance(ids, list) or not ids:
            raise ValueError("audience.users.ids must be a non-empty list")

    elif audience_type == "group_members":
        group_id = audience_spec.get("group_id")
        if not group_id:
            raise ValueError("audience.group_members.group_id is required")

    elif audience_type == "group_members_multi":
        group_ids = audience_spec.get("group_ids")
        if not isinstance(group_ids, list) or not group_ids:
            raise ValueError("audience.group_members_multi.group_ids must be a non-empty list")

    elif audience_type == "post_participants":
        post_id = audience_spec.get("post_id")
        if not post_id:
            raise ValueError("audience.post_participants.post_id is required")

    else:
        raise ValueError(f"unknown audience.type: {audience_type}")
