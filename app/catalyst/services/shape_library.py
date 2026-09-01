"""Shape Library adapter for Catalyst ingest.

Catalyst consumes Shape Library contracts from Puddlejump, but should not
hard-code strategy files throughout the ingest pipeline. This module keeps that
boundary small and explicit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _release_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _shape_root() -> Path:
    return _release_root() / "puddlejump" / "reference" / "shapes"


def _resolve_library_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if path.is_absolute():
        return path
    if path.parts[:2] == ("puddlejump", "reference"):
        return _release_root() / path
    return _shape_root() / path


@dataclass(frozen=True)
class ShapeLibraryStrategy:
    id: str
    version: str | None = None
    status: str | None = None
    domain: str | None = None
    source_shapes: list[str] = field(default_factory=list)
    primary_target: str | None = None
    secondary_targets: list[str] = field(default_factory=list)
    sectioning: str | None = None
    extraction_grain: str | None = None
    token_posture: str | None = None
    operator_intent: str | None = None
    validation: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    contract_file: str | None = None
    prose_file: str | None = None
    contract_loaded: bool = False
    companion_loaded: bool = False
    contract_gaps: list[dict[str, str]] = field(default_factory=list)

    def as_strategy_map_fields(self) -> dict[str, Any]:
        return {
            "strategy_id": self.id,
            "strategy_version": self.version,
            "strategy_status": self.status,
            "primary_target": self.primary_target,
            "secondary_targets": self.secondary_targets,
            "sectioning": self.sectioning,
            "extraction_grain": self.extraction_grain,
            "token_posture": self.token_posture,
            "operator_intent": self.operator_intent,
            "validation": self.validation,
            "failure_modes": self.failure_modes,
            "contract_file": self.contract_file,
            "prose_file": self.prose_file,
            "contract_loaded": self.contract_loaded,
            "companion_loaded": self.companion_loaded,
            "contract_gaps": self.contract_gaps,
        }


class ShapeLibrary:
    def __init__(self, manifest_path: Path | None = None):
        self.manifest_path = manifest_path or (_shape_root() / "manifest.yaml")
        self.manifest: dict[str, Any] = {}
        self.shape_ids: set[str] = set()
        self.strategies: dict[str, dict[str, Any]] = {}
        self.load_error: str | None = None
        self._load()

    def _load_yaml_file(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data if isinstance(data, dict) else {}

    def _load(self) -> None:
        try:
            self.manifest = self._load_yaml_file(self.manifest_path)
        except Exception as exc:
            self.load_error = str(exc)
            logger.warning("[shape-library] manifest load failed: %s", exc)
            return

        for vertical in self.manifest.get("verticals", []) or []:
            for shape in vertical.get("shapes", []) or []:
                shape_id = shape.get("id")
                if shape_id:
                    self.shape_ids.add(str(shape_id))

        for strategy_group in self.manifest.get("strategies", []) or []:
            for entry in strategy_group.get("entries", []) or []:
                strategy_id = entry.get("id")
                if strategy_id:
                    self.strategies[str(strategy_id)] = dict(entry)

    def get_strategy(self, strategy_id: str) -> ShapeLibraryStrategy | None:
        manifest_entry = self.strategies.get(strategy_id)
        if not manifest_entry:
            return None

        contract_path = _resolve_library_path(manifest_entry.get("contract_file"))
        contract: dict[str, Any] = {}
        contract_loaded = False
        gaps: list[dict[str, str]] = []

        if contract_path and contract_path.exists():
            try:
                contract = self._load_yaml_file(contract_path)
                contract_loaded = True
            except Exception as exc:
                gaps.append({"contract_gap": "strategy_contract_unreadable", "detail": str(exc)})
        else:
            gaps.append({"contract_gap": "missing_strategy_contract", "strategy_id": strategy_id})

        data = {**manifest_entry, **contract}
        source_shapes = [str(s) for s in (data.get("source_shapes") or [])]
        for shape_id in source_shapes:
            if shape_id not in self.shape_ids:
                gaps.append({"contract_gap": "missing_source_shape", "missing_shape": shape_id})

        for target_id in [data.get("primary_target"), *(data.get("secondary_targets") or [])]:
            if target_id and target_id not in self.shape_ids:
                gaps.append({"contract_gap": "missing_target_shape", "missing_shape": str(target_id)})

        prose_file = data.get("prose_file") or data.get("companion_md")
        prose_path = _resolve_library_path(prose_file)
        companion_loaded = bool(prose_path and prose_path.exists())
        if prose_file and not companion_loaded:
            gaps.append({"contract_gap": "missing_strategy_prose", "strategy_id": strategy_id})

        return ShapeLibraryStrategy(
            id=str(data.get("id") or strategy_id),
            version=str(data.get("version")) if data.get("version") is not None else None,
            status=data.get("status"),
            domain=data.get("domain"),
            source_shapes=source_shapes,
            primary_target=data.get("primary_target"),
            secondary_targets=[str(s) for s in (data.get("secondary_targets") or [])],
            sectioning=data.get("sectioning"),
            extraction_grain=data.get("extraction_grain"),
            token_posture=data.get("token_posture"),
            operator_intent=data.get("operator_intent"),
            validation=[str(v) for v in (data.get("validation") or [])],
            failure_modes=[str(f) for f in (data.get("failure_modes") or [])],
            contract_file=manifest_entry.get("contract_file"),
            prose_file=prose_file,
            contract_loaded=contract_loaded,
            companion_loaded=companion_loaded,
            contract_gaps=gaps,
        )


@lru_cache(maxsize=1)
def get_shape_library() -> ShapeLibrary:
    return ShapeLibrary()
