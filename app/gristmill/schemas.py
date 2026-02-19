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

COURSE_SCHEMA = {
    'type': 'course',
    'model': 'earthlab.Course',
    'required_fields': ['title'],
    'fields': {
        'title': {
            'type': 'string',
            'max_length': 100,
            'source': 'declaration',
        },
        'difficulty': {
            'type': 'choice',
            'choices': ['beginner', 'intermediate', 'advanced'],
            'maps_to': 'difficulty_level',
        },
        'delivery': {
            'type': 'choice',
            'choices': ['online', 'self_paced', 'hybrid', 'in_person'],
            'default': 'self_paced',
            'maps_to': 'delivery_type',
        },
        'duration': {
            'type': 'integer',
            'maps_to': 'estimated_duration',
        },
        'body': {
            'type': 'markdown',
            'multiline': True,
        },
    }
}

LESSON_SCHEMA = {
    'type': 'lesson',
    'model': 'earthlab.Lesson',
    'required_fields': ['title'],
    'fields': {
        'title': {
            'type': 'string',
            'max_length': 100,
            'source': 'declaration',
        },
        'difficulty': {
            'type': 'choice',
            'choices': ['beginner', 'intermediate', 'advanced'],
            'maps_to': 'difficulty_level',
        },
        'duration': {
            'type': 'integer',
            'maps_to': 'estimated_duration',
        },
        'body': {
            'type': 'markdown',
            'multiline': True,
        },
    }
}

SCHEMA_REGISTRY = {
    'event': EVENT_SCHEMA,
    'course': COURSE_SCHEMA,
    'lesson': LESSON_SCHEMA,
}