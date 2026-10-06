from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from uuid import UUID


class BaseStackroomAdapter(ABC):
    adapter_name: str = ""
    # Stackroom Artifact type for ingested text. None keeps Stackroom's default
    # ("extracted_text"); set it when retrieve needs to tell this content apart.
    artifact_type: str | None = None

    @abstractmethod
    def supports(self, obj) -> bool: ...

    @abstractmethod
    def build_text(self, obj) -> str: ...

    @abstractmethod
    def get_library_id(self, obj) -> UUID: ...

    @abstractmethod
    def get_source_path(self, obj) -> str: ...

    def get_filename(self, obj) -> str:
        return self.get_source_path(obj).split("/")[-1]

    def current_hash(self, obj) -> str:
        return hashlib.sha256(self.build_text(obj).encode("utf-8")).hexdigest()

    def should_reingest(self, sync_state, obj, *, force: bool = False) -> bool:
        if force:
            return True
        if sync_state.status != "synced":
            return True
        return self.current_hash(obj) != (sync_state.last_synced_hash or "")
