# Known signal marker types surfaced on the Console.
# raw_name values match what WritingMarkerOccurrence.raw_name stores after
# the regex detects /! /~ /? /@ in piece bodies.

SIGNAL_MARKER_REGISTRY = {
    "!": {
        "slug": "important",
        "label": "Important",
        "inverse_label": "Marked as important",
        "symbol": "/!",
    },
    "~": {
        "slug": "inprogress",
        "label": "In Progress",
        "inverse_label": "In motion",
        "symbol": "/~",
    },
    "?": {
        "slug": "question",
        "label": "Open Questions",
        "inverse_label": "Uncertain",
        "symbol": "/?",
    },
    "@": {
        "slug": "delegated",
        "label": "Waiting / Delegated",
        "inverse_label": "Delegating to",
        "symbol": "/@",
    },
}

SIGNAL_MARKER_NAMES = list(SIGNAL_MARKER_REGISTRY.keys())
