import time
import jwt
import uuid
import hashlib

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from mixtape.services.defaults import ensure_default_group
from stackroom.models import Library, SourceFile, Chunk, Artifact  # adjust imports to your actual models


User = get_user_model()


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def mint_service_jwt(sub) -> str:
    now = int(time.time())
    payload = {
        "iss": getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
        "aud": "django-ir",
        "sub": str(sub),
        "iat": now,
        "nbf": now,
        "exp": now + 600,
        "svc": "stackroom",
        "scope": "stackroom.ir.write",
    }
    return jwt.encode(payload, settings.SERVICE_JWT_SECRET, algorithm=getattr(settings, "SERVICE_JWT_ALG", "HS256"))


class TestIRPersistenceIdempotency(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service_user = User.objects.create_user(username="stackroom_service", password=None)

        default_group = ensure_default_group(sponsor_user=cls.service_user)
        library = Library(title="Default Library")
        library.set_sponsor(default_group)
        library.set_submitted_by(cls.service_user)
        library.author = cls.service_user
        library.author_name = cls.service_user.get_full_name() or cls.service_user.username
        library.save()

        cls.library_id = library.id

    def setUp(self):
        token = mint_service_jwt(self.service_user.pk)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_start_is_idempotent_by_library_and_hash(self):
        file_hash = sha256("same-content")

        payload = {
            "library_id": str(self.library_id),
            "origin": "upload",
            "path": "stackroom/test.md",
            "filename": "test.md",
            "content_type": "text/markdown",
            "size_bytes": 123,
            "hash_sha256": file_hash,
        }

        r1 = self.client.post("/api/stackroom/ingestion/start", payload, format="json")
        self.assertEqual(r1.status_code, 200)
        sf1 = r1.data["source_file_id"]

        r2 = self.client.post("/api/stackroom/ingestion/start", payload, format="json")
        self.assertEqual(r2.status_code, 200)
        sf2 = r2.data["source_file_id"]

        self.assertEqual(sf1, sf2)
        self.assertEqual(SourceFile.objects.filter(hash_sha256=file_hash).count(), 1)

    def test_chunks_are_idempotent_by_artifact_strategy_hash_irversion(self):
        # 1) start + artifact
        file_hash = sha256("content-v1")
        start = self.client.post(
            "/api/stackroom/ingestion/start",
            {
                "library_id": str(self.library_id),
                "origin": "upload",
                "path": "stackroom/test.md",
                "filename": "test.md",
                "content_type": "text/markdown",
                "size_bytes": 123,
                "hash_sha256": file_hash,
            },
            format="json",
        )
        self.assertEqual(start.status_code, 200)
        source_file_id = start.data["source_file_id"]

        art_id = str(uuid.uuid4())
        art = self.client.post(
            "/api/stackroom/artifacts/",
            {
                "id": art_id,
                "source_file_id": source_file_id,
                "artifact_type": "extracted_text",
                "format": "text/plain",
                "text": "hello world " * 50,
                "ir_version": "0.1",
            },
            format="json",
        )
        self.assertIn(art.status_code, (200, 201))

        # 2) bulk chunks (same payload twice)
        chunk_text = "hello world " * 10
        chunk_hash = sha256(chunk_text)

        chunks_payload = {
            "artifact_id": art_id,
            "chunk_strategy": "sliding_window",
            "ir_version": "0.1",
            "chunks": [
                {
                    "id": str(uuid.uuid4()),
                    "text": chunk_text,
                    "token_estimate": 50,
                    "order_index": 0,
                    "hash_sha256": chunk_hash,
                    "embedding_id": str(uuid.uuid4()),
                    "source_spans": [{"artifact_id": art_id, "char_start": 0, "char_end": 120}],
                }
            ],
        }

        c1 = self.client.post("/api/stackroom/chunks/bulk", chunks_payload, format="json")
        self.assertEqual(c1.status_code, 200)

        c2 = self.client.post("/api/stackroom/chunks/bulk", chunks_payload, format="json")
        self.assertEqual(c2.status_code, 200)

        # should still be 1 logical chunk row for that identity (even if "id" differs)
        self.assertEqual(
            Chunk.objects.filter(
                artifact_id=art_id,
                chunk_strategy="sliding_window",
                hash_sha256=chunk_hash,
                ir_version="0.1",
            ).count(),
            1,
        )
