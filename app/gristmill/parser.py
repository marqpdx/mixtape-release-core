# gristmill/parser.py

"""
Ultra-minimal Grist parser - v0.1
Handles ONLY: /event blocks with key: value lines
"""
import re
from datetime import datetime
from .schemas import SCHEMA_REGISTRY


def resolve_block_type(block_type: str) -> str:
    """Resolve block type, allowing short unique prefixes like /is -> /issue."""
    normalized = (block_type or "").strip().lower()
    if not normalized:
        return normalized
    if normalized in SCHEMA_REGISTRY:
        return normalized
    if len(normalized) < 2:
        return normalized

    matches = [key for key in SCHEMA_REGISTRY.keys() if key.startswith(normalized)]
    if len(matches) == 1:
        return matches[0]
    return normalized


def parse_grist(grist_text):
    """
    Parse Grist text into AST.
    Returns: {'blocks': [...], 'errors': [...]}
    """
    blocks = []
    current_block = None
    current_field = None
    current_value = []

    for line_num, line in enumerate(grist_text.split('\n'), 1):
        stripped = line.strip()

        # Block marker: /event Title Goes Here
        if stripped.startswith('/'):
            # Save previous block
            if current_block:
                blocks.append(current_block)

            # Split on first space to get type and title
            # "/event Weekly Meditation" → type="event", title="Weekly Meditation"
            parts = stripped[1:].split(None, 1)  # split on whitespace, max 1 split
            block_type = resolve_block_type(parts[0] if parts else '')
            title = parts[1].strip() if len(parts) > 1 else ''

            current_block = {
                'type': block_type,
                'title': title,  # Title from declaration line
                'fields': {},
                'errors': [],
                'line': line_num,
            }
            current_field = None
            current_value = []
            continue

        # Empty line
        if not stripped:
            continue

        # Field line: key: value
        if ':' in stripped and not line.startswith(' '):
            # Save previous multiline field
            if current_field and current_value:
                current_block['fields'][current_field] = '\n'.join(current_value)

            key, value = stripped.split(':', 1)
            key = key.strip()
            value = value.strip()

            if value:
                # Single-line field
                current_block['fields'][key] = value
                current_field = None
                current_value = []
            else:
                # Start of multiline field
                current_field = key
                current_value = []

        # Continuation of multiline field
        elif current_field:
            current_value.append(line)

    # Save last block
    if current_block:
        if current_field and current_value:
            current_block['fields'][current_field] = '\n'.join(current_value)
        blocks.append(current_block)

    # Validate each block
    for block in blocks:
        validate_block(block)

    return {'blocks': blocks}


def validate_block(block):
    """
    Validate block against schema.
    Adds errors to block['errors'].

    Note: 'title' is extracted from the block declaration line (/event Title Here),
    not from fields. All other required fields are checked in block['fields'].
    """
    block_type = block['type']
    schema = SCHEMA_REGISTRY.get(block_type)

    if not schema:
        block['errors'].append({
            'type': 'unknown_type',
            'message': f"Unknown block type: {block_type}"
        })
        return

    # Check title (from block declaration, not fields)
    if not block.get('title'):
        block['errors'].append({
            'field': 'title',
            'type': 'required',
            'message': f"Title is required. Use: /{block_type} Your Title Here"
        })

    # Check required fields (excluding 'title' since it's from declaration)
    for field in schema['required_fields']:
        if field == 'title':
            continue  # Title checked above
        if field not in block['fields']:
            block['errors'].append({
                'field': field,
                'type': 'required',
                'message': f"Required field '{field}' is missing"
            })

    # Type validation (basic)
    # Iterate over a list copy to avoid "dictionary changed size during iteration" error
    for field_name, value in list(block['fields'].items()):
        field_schema = schema['fields'].get(field_name)
        if not field_schema:
            block['errors'].append({
                'field': field_name,
                'type': 'unknown_field',
                'message': f"Unknown field: {field_name}"
            })
            continue

        # Datetime parsing
        if field_schema['type'] == 'datetime':
            try:
                # Try parsing
                datetime.strptime(value, '%Y-%m-%d %H:%M')
                block['fields'][field_name + '_parsed'] = value
            except ValueError:
                block['errors'].append({
                    'field': field_name,
                    'type': 'invalid_datetime',
                    'message': f"Invalid datetime format. Expected: YYYY-MM-DD HH:MM"
                })
