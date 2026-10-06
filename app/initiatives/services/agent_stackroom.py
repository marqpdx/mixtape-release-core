# initiatives/services/agent_stackroom.py
#
# Re-export shim. Retrieval now lives in stackroom_client/ (consolidated with
# inkwell/stackroom_http_client.py); new code should import from there.

from __future__ import annotations

from stackroom_client import StackroomClientError, mint_service_token
from stackroom_client import retrieve as retrieve_from_stackroom  # noqa: F401

# One error type for every Stackroom call; the old name stays importable.
AgentStackroomError = StackroomClientError


def _mint_stackroom_service_token(subject: str = "django") -> str:
    return mint_service_token(subject)
