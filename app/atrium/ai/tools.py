# atrium/ai/tools.py
#
# Tool schemas (Anthropic tool_use format) and dispatch for the Atrium
# read-only bridge: query_canon/get_document (Stage 1) + read_file/grep
# (Stage 1b). All tools are read-only — no write tool exists here by design.

from __future__ import annotations

import json
import logging

from atrium.ai import canon_client, codebase_tools

logger = logging.getLogger(__name__)

TOOLS = [
    {
        "name": "query_canon",
        "description": (
            "Semantic search over the Puddlejump canon (ADRs, decisions, status docs) "
            "for passages relevant to a natural-language query. Returns ranked chunks "
            "with source document metadata, including doc_uuid for use with get_document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query."},
                "limit": {"type": "integer", "description": "Max results to return (default 5)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_document",
        "description": (
            "Fetch the full text of a canon document by its doc_uuid "
            "(as returned in query_canon results)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_uuid": {"type": "string"},
            },
            "required": ["doc_uuid"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a file from the mixtape-release-core or mixtape-release-frontend "
            "codebase checkouts. Path must start with 'mixtape-release-core/' or "
            "'mixtape-release-frontend/'. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "grep",
        "description": (
            "Search for a regex pattern in a file or directory under the "
            "mixtape-release-core/mixtape-release-frontend checkouts. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression."},
                "path": {
                    "type": "string",
                    "description": "File or directory, relative, rooted at 'mixtape-release-core/' or 'mixtape-release-frontend/'.",
                },
            },
            "required": ["pattern", "path"],
        },
    },
]


def dispatch_tool(name: str, tool_input: dict) -> str:
    """Execute a tool call and return a JSON string suitable for a tool_result block."""
    try:
        if name == "query_canon":
            limit = int(tool_input.get("limit") or 5)
            return canon_client.query_canon(tool_input.get("query", ""), limit=limit)
        if name == "get_document":
            return canon_client.get_document(tool_input.get("doc_uuid", ""))
        if name == "read_file":
            return codebase_tools.read_file(tool_input.get("path", ""))
        if name == "grep":
            return codebase_tools.grep(tool_input.get("pattern", ""), tool_input.get("path", ""))
        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as exc:
        logger.warning("Atrium tool %r failed: %s", name, exc)
        return json.dumps({"error": str(exc)})
