# stackroom/tests/test_phase_12_spine_flow.py

from __future__ import annotations

import hashlib
import time
import uuid

import jwt
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from stackroom.models import Artifact, Chunk, IngestionReceipt, Library
from stackroom.tests.helpers import mint_stackroom_service_token


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ensure_service_user_exists(user_id: str) -> str:
    """
    ServiceJWTAuthentication requires User(pk=sub) to exist.
    Support both UUID primary keys and non-UUID PKs gracefully.
    Returns the actual pk string used in the token.
    """
    User = get_user_model()

    # If your CustomUser pk is a UUIDField, this will work.
    try:
        obj, _ = User.objects.get_or_create(pk=user_id)  # type: ignore[arg-type]
        return str(obj.pk)
    except Exception:
        # Fallback: create a user with default pk type (int, etc.)
        obj = User.objects.create()
        return str(obj.pk)


def _authed_client(settings) -> APIClient:
    """
    Create an APIClient authenticated with a valid Stackroom service JWT
    and ensure the service user exists.
    """
    # Ensure auth config is set (these are what ServiceJWTAuthentication reads)
    settings.SERVICE_JWT_SECRET = getattr(settings, "SERVICE_JWT_SECRET", None) or "test-secret"
    settings.SERVICE_JWT_ISS = getattr(settings, "SERVICE_JWT_ISS", None) or "mixtape"
    settings.SERVICE_JWT_AUD_IR = getattr(settings, "SERVICE_JWT_AUD_IR", None) or "django-ir"
    settings.SERVICE_JWT_ALG = getattr(settings, "SERVICE_JWT_ALG", None) or "HS256"

    desired_sub = getattr(settings, "STACKROOM_SERVICE_USER_ID", "") or str(uuid.uuid4())
    actual_sub = _ensure_service_user_exists(desired_sub)
    settings.STACKROOM_SERVICE_USER_ID = actual_sub

    token = mint_stackroom_service_token(user_id=actual_sub)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase_12_spine_end_to_end_idempotent(settings):
    """
    Mirrors the smoke flow:
      start -> artifact (idempotent) -> chunks (idempotent) -> complete (idempotent)
    """
    client = _authed_client(settings)

    # Create Library
    lib = Library.objects.create(tenant_type="user", tenant_id="dev", name="Stackroom Test Library")

    # Endpoints (no trailing slashes; APPEND_SLASH=False)
    start_url = "/api/stackroom/ingestion/start"
    artifacts_url = "/api/stackroom/artifacts"
    chunks_bulk_url = "/api/stackroom/chunks/bulk"
    complete_url = "/api/stackroom/ingestion/complete"

    # 1) Start
    start_payload = {
        "library_id": str(lib.id),
        "origin": "upload",
        "path": "smoke.txt",
        "filename": "smoke.txt",
        "hash_sha256": "deadbeef" * 8,
        "content_type": "text/plain",
        "size_bytes": 4,
        "ir_version": "0.1",
    }
    r = client.post(start_url, start_payload, format="json")
    assert r.status_code == 200, r.content
    run_id = r.data["ingestion_run_id"]
    source_file_id = r.data["source_file_id"]

    # 2) Artifact create (idempotent)
    artifact_uid = "extracted_text:v0.1"
    art_payload = {
        "ingestion_run_id": run_id,
        "source_file_id": source_file_id,
        "artifact_uid": artifact_uid,
        "artifact_type": "extracted_text",
        "format": "text/plain",
        "text": "Hello artifact",
        "storage_key": "",
        "ir_version": "0.1",
    }

    r1 = client.post(artifacts_url, art_payload, format="json")
    assert r1.status_code == 200, r1.content
    artifact_id_1 = r1.data["artifact_id"]
    assert r1.data["artifact_created"] is True

    r2 = client.post(artifacts_url, art_payload, format="json")
    assert r2.status_code == 200, r2.content
    artifact_id_2 = r2.data["artifact_id"]
    assert artifact_id_1 == artifact_id_2
    assert r2.data["artifact_created"] is False

    assert Artifact.objects.filter(id=artifact_id_1).count() == 1
    assert Artifact.objects.filter(source_file_id=source_file_id, artifact_uid=artifact_uid).count() == 1

    # 3) Chunks bulk create + retry (updates-on-retry)
    chunks_payload = {
        "ingestion_run_id": run_id,
        "artifact_id": artifact_id_1,
        "chunks": [
            {
                "chunk_strategy": "sliding_window",
                "text": "Chunk one text.",
                "token_estimate": 5,
                "order_index": 1,
                "source_spans": [{"char_start": 0, "char_end": 13}],
                "hash_sha256": _sha256_hex("chunk1"),
                "ir_version": "0.1",
                "embedding_id": "",
            },
            {
                "chunk_strategy": "sliding_window",
                "text": "Chunk two text.",
                "token_estimate": 5,
                "order_index": 2,
                "source_spans": [{"char_start": 14, "char_end": 27}],
                "hash_sha256": _sha256_hex("chunk2"),
                "ir_version": "0.1",
                "embedding_id": "",
            },
        ],
    }

    c1 = client.post(chunks_bulk_url, chunks_payload, format="json")
    assert c1.status_code == 200, c1.content
    assert c1.data["chunks_received"] == 2
    assert c1.data["chunks_created"] == 2
    assert c1.data["chunks_updated"] == 0
    assert Chunk.objects.filter(artifact_id=artifact_id_1).count() == 2

    c2 = client.post(chunks_bulk_url, chunks_payload, format="json")
    assert c2.status_code == 200, c2.content
    assert c2.data["chunks_received"] == 2
    assert c2.data["chunks_created"] == 0
    assert c2.data["chunks_updated"] == 2
    assert Chunk.objects.filter(artifact_id=artifact_id_1).count() == 2

    # 4) Complete + retry (receipt idempotency)
    comp_payload = {"ingestion_run_id": run_id, "status": "success", "errors": [], "warnings": [], "next_actions": []}

    rc1 = client.post(complete_url, comp_payload, format="json")
    assert rc1.status_code == 200, rc1.content
    assert rc1.data["status"] == "success"
    assert IngestionReceipt.objects.filter(run_id=run_id).count() == 1

    rc2 = client.post(complete_url, comp_payload, format="json")
    assert rc2.status_code == 200, rc2.content
    assert rc2.data["status"] == "success"
    assert IngestionReceipt.objects.filter(run_id=run_id).count() == 1


@pytest.mark.django_db
def test_ir_endpoints_require_bearer_token():
    client = APIClient()  # no auth
    lib = Library.objects.create(tenant_type="user", tenant_id="dev", name="NoAuth Lib")

    payload = {
        "library_id": str(lib.id),
        "origin": "upload",
        "path": "x.txt",
        "filename": "x.txt",
        "hash_sha256": "deadbeef" * 8,
        "content_type": "text/plain",
        "size_bytes": 1,
        "ir_version": "0.1",
    }

    r = client.post("/api/stackroom/ingestion/start", payload, format="json")
    assert r.status_code in (401, 403), r.content


@pytest.mark.django_db
def test_ir_endpoints_reject_wrong_audience(settings):
    # Expected audience in Django
    settings.SERVICE_JWT_SECRET = "test-secret"
    settings.SERVICE_JWT_ISS = "mixtape"
    settings.SERVICE_JWT_AUD_IR = "django-ir"
    settings.SERVICE_JWT_ALG = "HS256"

    sub = _ensure_service_user_exists(str(uuid.uuid4()))

    now = int(time.time())
    bad_token = jwt.encode(
        {
            "iss": settings.SERVICE_JWT_ISS,
            "aud": "not-django-ir",
            "sub": sub,
            "iat": now,
            "nbf": now - 5,
            "exp": now + 600,
            "svc": "stackroom",
            "scope": "stackroom.ir.write",
        },
        settings.SERVICE_JWT_SECRET,
        algorithm=settings.SERVICE_JWT_ALG,
    )

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {bad_token}")

    lib = Library.objects.create(tenant_type="user", tenant_id="dev", name="BadAud Lib")
    payload = {
        "library_id": str(lib.id),
        "origin": "upload",
        "path": "x.txt",
        "filename": "x.txt",
        "hash_sha256": "deadbeef" * 8,
        "content_type": "text/plain",
        "size_bytes": 1,
        "ir_version": "0.1",
    }

    r = client.post("/api/stackroom/ingestion/start", payload, format="json")
    assert r.status_code in (401, 403), r.content


@pytest.mark.django_db
def test_ir_endpoints_reject_wrong_scope(settings):
    # Start with a valid authed client, then swap token to a wrong-scope token.
    client = _authed_client(settings)

    sub = settings.STACKROOM_SERVICE_USER_ID
    now = int(time.time())
    bad_scope_token = jwt.encode(
        {
            "iss": settings.SERVICE_JWT_ISS,
            "aud": settings.SERVICE_JWT_AUD_IR,
            "sub": sub,
            "iat": now,
            "nbf": now - 5,
            "exp": now + 600,
            "svc": "stackroom",
            "scope": "nope",
        },
        settings.SERVICE_JWT_SECRET,
        algorithm=settings.SERVICE_JWT_ALG,
    )

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {bad_scope_token}")

    lib = Library.objects.create(tenant_type="user", tenant_id="dev", name="BadScope Lib")
    payload = {
        "library_id": str(lib.id),
        "origin": "upload",
        "path": "x.txt",
        "filename": "x.txt",
        "hash_sha256": "deadbeef" * 8,
        "content_type": "text/plain",
        "size_bytes": 1,
        "ir_version": "0.1",
    }

    r = client.post("/api/stackroom/ingestion/start", payload, format="json")
    assert r.status_code == 403, r.content


@pytest.mark.django_db
def test_run_state_blocks_writes_after_complete(settings):
    client = _authed_client(settings)

    lib = Library.objects.create(tenant_type="user", tenant_id="dev", name="RunState Lib")

    start_payload = {
        "library_id": str(lib.id),
        "origin": "upload",
        "path": "smoke.txt",
        "filename": "smoke.txt",
        "hash_sha256": "deadbeef" * 8,
        "content_type": "text/plain",
        "size_bytes": 4,
        "ir_version": "0.1",
    }
    r = client.post("/api/stackroom/ingestion/start", start_payload, format="json")
    assert r.status_code == 200, r.content
    run_id = r.data["ingestion_run_id"]
    source_file_id = r.data["source_file_id"]

    art_payload = {
        "ingestion_run_id": run_id,
        "source_file_id": source_file_id,
        "artifact_uid": "extracted_text:v0.1",
        "artifact_type": "extracted_text",
        "format": "text/plain",
        "text": "Hello artifact",
        "storage_key": "",
        "ir_version": "0.1",
    }
    ra = client.post("/api/stackroom/artifacts", art_payload, format="json")
    assert ra.status_code == 200, ra.content
    artifact_id = ra.data["artifact_id"]

    comp_payload = {"ingestion_run_id": run_id, "status": "success", "errors": [], "warnings": [], "next_actions": []}
    rc = client.post("/api/stackroom/ingestion/complete", comp_payload, format="json")
    assert rc.status_code == 200, rc.content

    # After completion, further writes should be blocked
    r_again = client.post("/api/stackroom/artifacts", art_payload, format="json")
    assert r_again.status_code == 409, r_again.content

    chunks_payload = {
        "ingestion_run_id": run_id,
        "artifact_id": artifact_id,
        "chunks": [
            {
                "chunk_strategy": "sliding_window",
                "text": "Chunk one text.",
                "token_estimate": 5,
                "order_index": 1,
                "source_spans": [{"char_start": 0, "char_end": 13}],
                "hash_sha256": _sha256_hex("chunk1"),
                "ir_version": "0.1",
                "embedding_id": "",
            },
        ],
    }
    c_again = client.post("/api/stackroom/chunks/bulk", chunks_payload, format="json")
    assert c_again.status_code == 409, c_again.content


@pytest.mark.django_db
def test_counters_do_not_inflate_on_idempotent_retries(settings):
    client = _authed_client(settings)

    lib = Library.objects.create(tenant_type="user", tenant_id="dev", name="Counters Lib")
    start_payload = {
        "library_id": str(lib.id),
        "origin": "upload",
        "path": "smoke.txt",
        "filename": "smoke.txt",
        "hash_sha256": "deadbeef" * 8,
        "content_type": "text/plain",
        "size_bytes": 4,
        "ir_version": "0.1",
    }
    r = client.post("/api/stackroom/ingestion/start", start_payload, format="json")
    assert r.status_code == 200, r.content
    run_id = r.data["ingestion_run_id"]
    source_file_id = r.data["source_file_id"]

    # Artifact twice -> artifacts_created should increase only once
    art_payload = {
        "ingestion_run_id": run_id,
        "source_file_id": source_file_id,
        "artifact_uid": "extracted_text:v0.1",
        "artifact_type": "extracted_text",
        "format": "text/plain",
        "text": "Hello artifact",
        "storage_key": "",
        "ir_version": "0.1",
    }
    r1 = client.post("/api/stackroom/artifacts", art_payload, format="json")
    r2 = client.post("/api/stackroom/artifacts", art_payload, format="json")
    assert r1.status_code == 200 and r2.status_code == 200
    artifact_id = r1.data["artifact_id"]

    # Chunks twice -> receipt counter should reflect only created count
    chunks_payload = {
        "ingestion_run_id": run_id,
        "artifact_id": artifact_id,
        "chunks": [
            {
                "chunk_strategy": "sliding_window",
                "text": "Chunk one text.",
                "token_estimate": 5,
                "order_index": 1,
                "source_spans": [{"char_start": 0, "char_end": 13}],
                "hash_sha256": _sha256_hex("chunk1"),
                "ir_version": "0.1",
                "embedding_id": "",
            },
            {
                "chunk_strategy": "sliding_window",
                "text": "Chunk two text.",
                "token_estimate": 5,
                "order_index": 2,
                "source_spans": [{"char_start": 14, "char_end": 27}],
                "hash_sha256": _sha256_hex("chunk2"),
                "ir_version": "0.1",
                "embedding_id": "",
            },
        ],
    }
    c1 = client.post("/api/stackroom/chunks/bulk", chunks_payload, format="json")
    c2 = client.post("/api/stackroom/chunks/bulk", chunks_payload, format="json")
    assert c1.status_code == 200 and c2.status_code == 200

    comp_payload = {"ingestion_run_id": run_id, "status": "success", "errors": [], "warnings": [], "next_actions": []}
    rc = client.post("/api/stackroom/ingestion/complete", comp_payload, format="json")
    assert rc.status_code == 200, rc.content

    assert rc.data["artifacts_created"] == 1
    assert rc.data["chunks_indexed"] == 2
