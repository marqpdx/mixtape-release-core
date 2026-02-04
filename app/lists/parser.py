"""
List Grammar Parser

Parses the plaintext micro-grammar used in Lists:

Line prefixes:
    - item       = open action item
    x item       = completed action item
    * item       = note/bullet (no completion semantics)

Sub-items:
    Two-space indent, one level only.

Inline directives:
    /due <date> - attaches a due date to the item
    Examples: /due tomorrow, /due 4/15, /due next Friday 5pm

Example:
    - call Alice /due tomorrow
    x send report
    * meeting notes
      * discussed Q2 goals
    - follow up /due next Monday
      - with Bob
      - with Carol
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Tuple
import re

from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta


class ItemType(str, Enum):
    """Type of list item."""
    ACTION_OPEN = "action_open"      # - item
    ACTION_DONE = "action_done"      # x item
    NOTE = "note"                    # * item


@dataclass
class DueInfo:
    """Parsed due date information."""
    raw: str  # Original text after /due (e.g., "tomorrow 7pm")
    parsed: Optional[datetime] = None  # Parsed datetime if successful
    needs_review: bool = False  # True if parsing failed or was ambiguous

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "parsed": self.parsed.isoformat() if self.parsed else None,
            "needs_review": self.needs_review,
        }


@dataclass
class ListItem:
    """A single item in a list."""
    item_type: ItemType
    text: str  # Text WITHOUT the /due directive (display text)
    text_raw: str  # Original text WITH /due directive (for serialization)
    index: int  # Position in flat list (for API operations)
    children: List["ListItem"] = field(default_factory=list)
    parent_index: Optional[int] = None  # Index of parent item, if sub-item
    due: Optional[DueInfo] = None  # Parsed due date info

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "type": self.item_type.value,
            "text": self.text,
            "text_raw": self.text_raw,
            "index": self.index,
            "parent_index": self.parent_index,
            "children": [child.to_dict() for child in self.children],
            "is_completed": self.item_type == ItemType.ACTION_DONE,
            "is_action": self.item_type in (ItemType.ACTION_OPEN, ItemType.ACTION_DONE),
            "due": self.due.to_dict() if self.due else None,
        }
        return result


# Regex patterns for line parsing
OPEN_PATTERN = re.compile(r"^- (.*)$")
DONE_PATTERN = re.compile(r"^x (.*)$")
NOTE_PATTERN = re.compile(r"^\* (.*)$")
SUB_OPEN_PATTERN = re.compile(r"^  - (.*)$")
SUB_DONE_PATTERN = re.compile(r"^  x (.*)$")
SUB_NOTE_PATTERN = re.compile(r"^  \* (.*)$")

# Pattern for /due directive - captures everything after /due
DUE_PATTERN = re.compile(r"\s*/due\s+(.+)$", re.IGNORECASE)

# Relative date keywords (case-insensitive)
RELATIVE_DATES = {
    "today": lambda now: now.replace(hour=23, minute=59, second=59, microsecond=0),
    "tomorrow": lambda now: (now + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0),
    "yesterday": lambda now: (now - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0),
    "next week": lambda now: (now + timedelta(weeks=1)).replace(hour=23, minute=59, second=59, microsecond=0),
    "next month": lambda now: (now + relativedelta(months=1)).replace(hour=23, minute=59, second=59, microsecond=0),
}

# Day of week mapping
WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def _parse_due_date(due_text: str, reference_date: Optional[datetime] = None) -> Tuple[Optional[datetime], bool]:
    """
    Parse a due date string into a datetime.

    Args:
        due_text: The text after /due (e.g., "tomorrow 7pm", "4/15", "next Friday")
        reference_date: Reference date for relative dates (defaults to now)

    Returns:
        Tuple of (parsed_datetime, needs_review)
        - If parsing succeeds: (datetime, False)
        - If parsing fails or is ambiguous: (None, True)
    """
    if not due_text:
        return None, True

    now = reference_date or datetime.now()
    due_lower = due_text.lower().strip()

    # Try relative date keywords first
    for keyword, calc in RELATIVE_DATES.items():
        if due_lower.startswith(keyword):
            base_date = calc(now)
            # Check for time suffix (e.g., "tomorrow 7pm")
            remainder = due_lower[len(keyword):].strip()
            if remainder:
                try:
                    time_part = dateutil_parser.parse(remainder, fuzzy=True)
                    base_date = base_date.replace(
                        hour=time_part.hour,
                        minute=time_part.minute,
                        second=0,
                        microsecond=0,
                    )
                except (ValueError, TypeError):
                    pass  # Keep default time
            return base_date, False

    # Try "next <weekday>" pattern
    next_match = re.match(r"next\s+(\w+)(?:\s+(.+))?", due_lower)
    if next_match:
        day_name = next_match.group(1)
        time_part = next_match.group(2)
        if day_name in WEEKDAYS:
            target_weekday = WEEKDAYS[day_name]
            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            result = (now + timedelta(days=days_ahead)).replace(
                hour=23, minute=59, second=59, microsecond=0
            )
            if time_part:
                try:
                    parsed_time = dateutil_parser.parse(time_part, fuzzy=True)
                    result = result.replace(
                        hour=parsed_time.hour,
                        minute=parsed_time.minute,
                        second=0,
                        microsecond=0,
                    )
                except (ValueError, TypeError):
                    pass
            return result, False

    # Try "<weekday>" without "next" (assumes this week or next)
    first_word = due_lower.split()[0] if due_lower else ""
    if first_word in WEEKDAYS:
        target_weekday = WEEKDAYS[first_word]
        days_ahead = target_weekday - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        result = (now + timedelta(days=days_ahead)).replace(
            hour=23, minute=59, second=59, microsecond=0
        )
        remainder = due_lower[len(first_word):].strip()
        if remainder:
            try:
                parsed_time = dateutil_parser.parse(remainder, fuzzy=True)
                result = result.replace(
                    hour=parsed_time.hour,
                    minute=parsed_time.minute,
                    second=0,
                    microsecond=0,
                )
            except (ValueError, TypeError):
                pass
        return result, False

    # Try dateutil parser for standard date formats
    try:
        parsed = dateutil_parser.parse(due_text, fuzzy=True, dayfirst=False)
        # If no year was specified and the date is in the past, assume next year
        if parsed.year == now.year and parsed < now:
            # Check if the original text contains a year
            if not re.search(r"\b(19|20)\d{2}\b", due_text):
                parsed = parsed.replace(year=parsed.year + 1)
        return parsed, False
    except (ValueError, TypeError):
        pass

    # Parsing failed - mark as needs review
    return None, True


def _extract_due_directive(text: str, reference_date: Optional[datetime] = None) -> Tuple[str, Optional[DueInfo]]:
    """
    Extract /due directive from item text.

    Args:
        text: Full item text (may contain /due directive)
        reference_date: Reference date for relative dates

    Returns:
        Tuple of (text_without_due, DueInfo or None)
    """
    match = DUE_PATTERN.search(text)
    if not match:
        return text, None

    due_raw = match.group(1).strip()
    text_without_due = text[:match.start()].strip()

    parsed_date, needs_review = _parse_due_date(due_raw, reference_date)

    due_info = DueInfo(
        raw=due_raw,
        parsed=parsed_date,
        needs_review=needs_review,
    )

    return text_without_due, due_info


def _parse_line(line: str, is_sub: bool = False) -> Optional[tuple[ItemType, str]]:
    """
    Parse a single line and return (ItemType, text) or None if not a valid item.
    """
    if is_sub:
        patterns = [
            (SUB_OPEN_PATTERN, ItemType.ACTION_OPEN),
            (SUB_DONE_PATTERN, ItemType.ACTION_DONE),
            (SUB_NOTE_PATTERN, ItemType.NOTE),
        ]
    else:
        patterns = [
            (OPEN_PATTERN, ItemType.ACTION_OPEN),
            (DONE_PATTERN, ItemType.ACTION_DONE),
            (NOTE_PATTERN, ItemType.NOTE),
        ]

    for pattern, item_type in patterns:
        match = pattern.match(line)
        if match:
            return (item_type, match.group(1))

    return None


def parse_list_text(text: str, reference_date: Optional[datetime] = None) -> List[ListItem]:
    """
    Parse list body_text into structured items.

    Returns a flat list of ListItem objects. Parent items have their children
    in the `children` field. Sub-items also have `parent_index` set.

    Args:
        text: The canonical body_text of a list
        reference_date: Reference date for relative due dates (defaults to now)

    Returns:
        List of top-level ListItem objects (sub-items nested in children)
    """
    if not text:
        return []

    lines = text.split("\n")
    items: List[ListItem] = []
    flat_index = 0
    current_parent: Optional[ListItem] = None
    current_parent_index: Optional[int] = None

    for line in lines:
        # Skip empty lines
        if not line.strip():
            continue

        # Check if it's a sub-item (starts with two spaces)
        if line.startswith("  "):
            parsed = _parse_line(line, is_sub=True)
            if parsed and current_parent is not None:
                item_type, item_text_raw = parsed
                # Extract /due directive
                item_text, due_info = _extract_due_directive(item_text_raw, reference_date)
                child = ListItem(
                    item_type=item_type,
                    text=item_text,
                    text_raw=item_text_raw,
                    index=flat_index,
                    parent_index=current_parent_index,
                    due=due_info,
                )
                current_parent.children.append(child)
                flat_index += 1
            # If no current parent, skip malformed sub-item
            continue

        # Top-level item
        parsed = _parse_line(line, is_sub=False)
        if parsed:
            item_type, item_text_raw = parsed
            # Extract /due directive
            item_text, due_info = _extract_due_directive(item_text_raw, reference_date)
            item = ListItem(
                item_type=item_type,
                text=item_text,
                text_raw=item_text_raw,
                index=flat_index,
                due=due_info,
            )
            items.append(item)
            current_parent = item
            current_parent_index = flat_index
            flat_index += 1

    return items


def serialize_list_items(items: List[ListItem]) -> str:
    """
    Convert structured items back to canonical text format.

    Uses text_raw to preserve /due directives and other inline metadata.

    Args:
        items: List of top-level ListItem objects (with children)

    Returns:
        Canonical body_text string
    """
    lines: List[str] = []

    for item in items:
        # Serialize top-level item (use text_raw to preserve /due directives)
        prefix = _get_prefix(item.item_type)
        lines.append(f"{prefix}{item.text_raw}")

        # Serialize children
        for child in item.children:
            child_prefix = _get_prefix(child.item_type)
            lines.append(f"  {child_prefix}{child.text_raw}")

    return "\n".join(lines)


def _get_prefix(item_type: ItemType) -> str:
    """Get the line prefix for an item type."""
    if item_type == ItemType.ACTION_OPEN:
        return "- "
    elif item_type == ItemType.ACTION_DONE:
        return "x "
    else:
        return "* "


def toggle_item_completion(items: List[ListItem], index: int) -> List[ListItem]:
    """
    Toggle an item's completion status (- ↔ x).

    Note items (*) cannot be toggled.

    Args:
        items: List of top-level ListItem objects
        index: Flat index of the item to toggle

    Returns:
        Updated list of items

    Raises:
        ValueError: If index not found or item is a note
    """
    # Find the item by flat index
    for item in items:
        if item.index == index:
            if item.item_type == ItemType.NOTE:
                raise ValueError("Cannot toggle completion on note items")
            item.item_type = (
                ItemType.ACTION_DONE
                if item.item_type == ItemType.ACTION_OPEN
                else ItemType.ACTION_OPEN
            )
            return items

        for child in item.children:
            if child.index == index:
                if child.item_type == ItemType.NOTE:
                    raise ValueError("Cannot toggle completion on note items")
                child.item_type = (
                    ItemType.ACTION_DONE
                    if child.item_type == ItemType.ACTION_OPEN
                    else ItemType.ACTION_OPEN
                )
                return items

    raise ValueError(f"Item with index {index} not found")


def reorder_items(items: List[ListItem], from_index: int, to_index: int) -> List[ListItem]:
    """
    Reorder a top-level item (with its children) to a new position.

    Args:
        items: List of top-level ListItem objects
        from_index: Current position in top-level list (0-based)
        to_index: Target position in top-level list (0-based)

    Returns:
        Reordered list of items with flat indices updated

    Raises:
        ValueError: If indices are out of bounds
    """
    if from_index < 0 or from_index >= len(items):
        raise ValueError(f"from_index {from_index} out of bounds")
    if to_index < 0 or to_index > len(items):
        raise ValueError(f"to_index {to_index} out of bounds")

    # Remove item from current position
    item = items.pop(from_index)

    # Adjust to_index if needed (since we removed an item)
    if to_index > from_index:
        to_index -= 1

    # Insert at new position
    items.insert(to_index, item)

    # Reindex all items
    _reindex_items(items)

    return items


def _reindex_items(items: List[ListItem]) -> None:
    """Update flat indices for all items after reordering."""
    flat_index = 0
    for i, item in enumerate(items):
        item.index = flat_index
        item.parent_index = None
        flat_index += 1

        for child in item.children:
            child.index = flat_index
            child.parent_index = item.index
            flat_index += 1


def get_item_by_index(items: List[ListItem], index: int) -> Optional[ListItem]:
    """Find an item by its flat index."""
    for item in items:
        if item.index == index:
            return item
        for child in item.children:
            if child.index == index:
                return child
    return None


def count_items(items: List[ListItem]) -> dict:
    """
    Count items by type and completion status.

    Returns:
        Dict with counts: total, open, done, notes
    """
    total = 0
    open_count = 0
    done_count = 0
    note_count = 0

    for item in items:
        total += 1
        if item.item_type == ItemType.ACTION_OPEN:
            open_count += 1
        elif item.item_type == ItemType.ACTION_DONE:
            done_count += 1
        else:
            note_count += 1

        for child in item.children:
            total += 1
            if child.item_type == ItemType.ACTION_OPEN:
                open_count += 1
            elif child.item_type == ItemType.ACTION_DONE:
                done_count += 1
            else:
                note_count += 1

    return {
        "total": total,
        "open": open_count,
        "done": done_count,
        "notes": note_count,
    }
