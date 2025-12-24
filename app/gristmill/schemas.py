# gristmill/schemas.py

"""
Ultra-minimal schema registry - just Event for reference implementation.

SYNTAX NOTE:
- Title comes from the block declaration line: /event Your Title Here
- All other fields use key: value syntax
- Example:
    /event Weekly Meditation
    start: 2025-01-15 18:00
    location: Main Hall
"""

EVENT_SCHEMA = {
    'type': 'event',
    'model': 'almanac.Event',
    'required_fields': ['title', 'start', 'location'],
    'fields': {
        'title': {
            'type': 'string',
            'max_length': 100,
            'source': 'declaration',  # From /event Title, not from fields
        },
        'start': {
            'type': 'datetime',
            'format': 'YYYY-MM-DD HH:MM',
        },
        'location': {
            'type': 'string',
            'max_length': 300,
        },
        'format': {
            'type': 'choice',
            'choices': ['workshop', 'lecture', 'discussion', 'social'],
            'default': 'workshop',
            'maps_to': 'event_format',
        },
        'body': {
            'type': 'markdown',
            'multiline': True,
        }
    }
}

SCHEMA_REGISTRY = {
    'event': EVENT_SCHEMA,
}