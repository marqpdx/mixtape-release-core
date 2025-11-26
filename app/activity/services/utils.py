# activity/services/utils.py
"""
Activity Service Utilities

Common utility functions for the activity subsystem.
"""


def max_priority(p1: str, p2: str) -> str:
    """
    Return the higher priority between two priority strings.

    Priority ordering: critical > normal > low

    Args:
        p1: First priority ("critical", "normal", or "low")
        p2: Second priority ("critical", "normal", or "low")

    Returns:
        The higher priority string

    Examples:
        >>> max_priority("critical", "normal")
        "critical"
        >>> max_priority("low", "normal")
        "normal"
        >>> max_priority("normal", "normal")
        "normal"
    """
    priority_map = {
        "critical": 3,
        "normal": 2,
        "low": 1
    }

    p1_value = priority_map.get(p1, 0)
    p2_value = priority_map.get(p2, 0)

    if p1_value >= p2_value:
        return p1
    return p2


def truncate_text(text: str, max_length: int = 140, suffix: str = "...") -> str:
    """
    Truncate text to a maximum length, adding suffix if truncated.

    Args:
        text: Text to truncate
        max_length: Maximum length (including suffix)
        suffix: String to append if truncated (default: "...")

    Returns:
        Truncated text

    Examples:
        >>> truncate_text("Hello world", 5)
        "He..."
        >>> truncate_text("Hello", 10)
        "Hello"
    """
    if len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix


def build_dedupe_key(prefix: str, *parts) -> str:
    """
    Build a dedupe key from parts.

    Args:
        prefix: Key prefix (e.g., "chat-mention", "post")
        *parts: Additional parts to join

    Returns:
        Dedupe key string

    Examples:
        >>> build_dedupe_key("chat-mention", "conv-123", "msg-456")
        "chat-mention:conv-123:msg-456"
    """
    return ":".join([prefix] + [str(p) for p in parts])


def build_aggregate_key(prefix: str, *parts, time_bucket: str = None) -> str:
    """
    Build an aggregate key from parts, optionally including a time bucket.

    Args:
        prefix: Key prefix (e.g., "comments", "mentions")
        *parts: Additional parts to join
        time_bucket: Optional time bucket string (e.g., "20250125", "202501251430")

    Returns:
        Aggregate key string

    Examples:
        >>> build_aggregate_key("comments", "post-123", time_bucket="20250125")
        "comments:post-123:20250125"
    """
    key_parts = [prefix] + [str(p) for p in parts]
    if time_bucket:
        key_parts.append(time_bucket)
    return ":".join(key_parts)
