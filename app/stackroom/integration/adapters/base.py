from __future__ import annotations

from abc import ABC, abstractmethod


class BaseStackroomAdapter(ABC):
    adapter_name = ""

    @abstractmethod
    def supports(self, obj) -> bool:
        raise NotImplementedError

    @abstractmethod
    def current_hash(self, obj) -> str:
        raise NotImplementedError

    @abstractmethod
    def ingest_local(self, obj, sync_state, *, reason: str) -> dict:
        raise NotImplementedError

    def should_reingest(self, sync_state, obj, *, force: bool = False) -> bool:
        if force:
            return True
        current_hash = self.current_hash(obj)
        if sync_state.status != "synced":
            return True
        return current_hash != (sync_state.last_synced_hash or "")

    def deactivate_local(self, obj, sync_state, *, reason: str) -> dict:
        raise NotImplementedError("Adapter does not support deactivation yet")
