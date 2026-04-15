from __future__ import annotations

from abc import ABC, abstractmethod

from stackroom.models import SourceFile


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

    def get_or_reuse_source_file(
        self,
        *,
        library,
        source_path: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        hash_sha256: str,
        created_by,
        origin: str = "external",
    ):
        source_file = SourceFile.objects.filter(library=library, path=source_path).first()
        if source_file is not None:
            if source_file.hash_sha256 == hash_sha256:
                return source_file

            duplicate = SourceFile.objects.filter(
                library=library,
                hash_sha256=hash_sha256,
            ).exclude(id=source_file.id).first()
            if duplicate is not None:
                return duplicate

            source_file.hash_sha256 = hash_sha256
            source_file.filename = filename
            source_file.content_type = content_type
            source_file.size_bytes = size_bytes
            source_file.created_by = source_file.created_by or created_by
            source_file.save(
                update_fields=[
                    "hash_sha256",
                    "filename",
                    "content_type",
                    "size_bytes",
                    "created_by",
                    "updated_at",
                ]
            )
            return source_file

        duplicate = SourceFile.objects.filter(
            library=library,
            hash_sha256=hash_sha256,
        ).first()
        if duplicate is not None:
            return duplicate

        return SourceFile.objects.create(
            library=library,
            origin=origin,
            path=source_path,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            hash_sha256=hash_sha256,
            created_by=created_by,
        )
