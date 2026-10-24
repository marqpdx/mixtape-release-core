"""Generic envelope mechanics Heddle owns (D7): the source fingerprint
and the Reading registry. Shape and meaning checks stay with each
surface's own contract module (D9 — Contour is the source for Shapes;
nothing surface-specific lives here)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable


def source_digest(sources: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sources, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Reading:
    """One surface's wiring into Heddle's generic lifecycle (D1-D4).

    capability/tool_name/version/prompt_version/units mirror the
    surface's own contract constants; build_prompt/response_schema/
    validate_findings are the surface's Shape and meaning checks (D7);
    resolvable_shape_ids names which Sighting shapes get an empty
    resolution slot left for the surface's own matching (D6);
    callback_task/callback_queue/cloud_setting_name are the surface's
    existing dispatch wiring, unchanged by this extraction.
    """
    capability: str
    tool_name: str
    version: str
    prompt_version: str
    units: tuple[str, ...]
    cloud_setting_name: str
    build_prompt: Callable[[list[dict], dict | None], str]
    response_schema: dict
    validate_findings: Callable[[dict, list[dict]], dict]
    resolvable_shape_ids: frozenset[str]
    callback_task: str
    callback_queue: str = "catalyst"


_REGISTRY: dict[str, Reading] = {}


def register(reading: Reading) -> None:
    _REGISTRY[reading.capability] = reading


def get(capability: str) -> Reading:
    return _REGISTRY[capability]
