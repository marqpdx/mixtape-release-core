# stackroom/tests/test_puddlejump_api.py

import io
import json
import zipfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase, APIClient


User = get_user_model()


def _make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for path, content in files.items():
            zip_file.writestr(path, content)
    return buffer.getvalue()


def _manifest_payload(*, bundle_id: str, files: list[dict]) -> dict:
    return {
        "format_version": "1.0.0",
        "bundle": {
            "id": bundle_id,
            "title": "Test Bundle",
            "created_at": "2026-01-12T14:30:00Z",
            "created_by": "test@example.com",
        },
        "constraints": {
            "max_files": 300,
            "format": "markdown",
            "folder_depth": 5,
        },
        "files": files,
        "integrity": {
            "catalog_hash": "sha256:abc",
            "total_hash": "sha256:def",
            "algorithm": "sha256",
        },
        "generation": {
            "tool": "test",
            "version": "1.0.0",
        },
    }


class PuddlejumpAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="puddlejump-user",
            email="puddlejump@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=self.user)

    def _upload(self, file_bytes: bytes, name: str, extra_fields: dict | None = None):
        payload = {"file": SimpleUploadedFile(name, file_bytes)}
        if extra_fields:
            payload.update(extra_fields)
        return self.client.post(
            "/api/stackroom/puddlejump/import/",
            data=payload,
            format="multipart",
        )

    def _assert_success_response(self, response, *, bundle_id: str, file_count: int):
        if "valid" in response.data:
            self.assertTrue(response.data["valid"])
            self.assertEqual(response.data["bundle_id"], bundle_id)
            self.assertEqual(response.data["validation_results"]["file_count"], file_count)
            return

        self.assertEqual(response.data["bundle_id"], bundle_id)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["counts"]["total_files"], file_count)

    def test_health_endpoint(self):
        client = APIClient()
        response = client.get("/api/stackroom/puddlejump/health")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")
        self.assertIn("import", response.data["endpoints"])

    def test_import_requires_auth(self):
        bundle = _make_zip({"puddlejump.json": b"{}", "PUDDLEJUMP.md": b"# Catalog"})
        client = APIClient()
        response = client.post(
            "/api/stackroom/puddlejump/import/",
            data={"file": SimpleUploadedFile("bundle.zip", bundle)},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_file(self):
        response = self.client.post(
            "/api/stackroom/puddlejump/import/",
            data={},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", response.data["errors"])

    def test_rejects_non_zip(self):
        response = self._upload(b"not a zip", "test.txt")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only .zip files are supported", response.data["errors"]["file"][0])

    def test_rejects_oversized_zip(self):
        oversized = b"0" * (52_428_800 + 1)
        response = self._upload(oversized, "large.zip")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("exceeds maximum of 50MB", response.data["errors"]["file"][0])

    def test_rejects_invalid_zip(self):
        response = self._upload(b"not really a zip", "fake.zip")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["field"], "file")

    def test_missing_manifest(self):
        bundle = _make_zip({
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/test.md": b"# Test",
        })
        response = self._upload(bundle, "missing-manifest.zip")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["field"], "manifest")

    def test_missing_catalog(self):
        bundle = _make_zip({
            "puddlejump.json": json.dumps(_manifest_payload(
                bundle_id="test-123",
                files=[],
            )).encode("utf-8"),
            "Documents/test.md": b"# Test",
        })
        response = self._upload(bundle, "missing-catalog.zip")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["field"], "catalog")

    def test_missing_documents_dir(self):
        bundle = _make_zip({
            "puddlejump.json": json.dumps(_manifest_payload(
                bundle_id="test-123",
                files=[],
            )).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
        })
        response = self._upload(bundle, "missing-docs.zip")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["field"], "structure")

    def test_invalid_manifest_json(self):
        bundle = _make_zip({
            "puddlejump.json": b"{ not json",
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/test.md": b"# Test",
        })
        response = self._upload(bundle, "bad-json.zip")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["field"], "manifest")

    def test_missing_required_manifest_fields(self):
        bundle = _make_zip({
            "puddlejump.json": json.dumps({"format_version": "1.0.0"}).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/test.md": b"# Test",
        })
        response = self._upload(bundle, "missing-fields.zip")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        messages = [err["message"] for err in response.data["errors"]]
        self.assertTrue(any("Missing required field in manifest" in msg for msg in messages))

    def test_rejects_too_many_files(self):
        docs = {
            f"Documents/file-{i}.md": b"# Test"
            for i in range(1, 302)
        }
        manifest = _manifest_payload(
            bundle_id="test-123",
            files=[],
        )
        docs.update({
            "puddlejump.json": json.dumps(manifest).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
        })
        response = self._upload(_make_zip(docs), "too-many.zip")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["field"], "file_count")
        self.assertEqual(response.data["errors"][0]["actual"], 301)

    def test_rejects_non_markdown_files(self):
        manifest = _manifest_payload(
            bundle_id="test-123",
            files=[],
        )
        bundle = _make_zip({
            "puddlejump.json": json.dumps(manifest).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/test.md": b"# Test",
            "Documents/bad.txt": b"nope",
        })
        response = self._upload(bundle, "bad-files.zip")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["field"], "file_format")

    def test_accepts_valid_minimal_bundle(self):
        manifest = _manifest_payload(
            bundle_id="550e8400-e29b-41d4-a716-446655440000",
            files=[{"path": "test.md", "hash": "sha256:abc", "size_bytes": 10}],
        )
        bundle = _make_zip({
            "puddlejump.json": json.dumps(manifest).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/test.md": b"# Test",
        })
        response = self._upload(bundle, "valid.zip")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._assert_success_response(
            response,
            bundle_id=manifest["bundle"]["id"],
            file_count=1,
        )

    def test_accepts_multi_file_bundle(self):
        manifest = _manifest_payload(
            bundle_id="650e8400-e29b-41d4-a716-446655440001",
            files=[
                {"path": "guides/onboarding.md", "hash": "sha256:111", "size_bytes": 10},
                {"path": "guides/deployment.md", "hash": "sha256:222", "size_bytes": 10},
                {"path": "specs/api.md", "hash": "sha256:333", "size_bytes": 10},
            ],
        )
        bundle = _make_zip({
            "puddlejump.json": json.dumps(manifest).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/guides/onboarding.md": b"# Onboarding",
            "Documents/guides/deployment.md": b"# Deployment",
            "Documents/specs/api.md": b"# API",
        })
        response = self._upload(bundle, "multi.zip")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._assert_success_response(
            response,
            bundle_id=manifest["bundle"]["id"],
            file_count=3,
        )

    def test_accepts_optional_params(self):
        manifest = _manifest_payload(
            bundle_id="750e8400-e29b-41d4-a716-446655440002",
            files=[{"path": "test.md", "hash": "sha256:abc", "size_bytes": 10}],
        )
        bundle = _make_zip({
            "puddlejump.json": json.dumps(manifest).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/test.md": b"# Test",
        })
        response = self._upload(
            bundle,
            "valid-params.zip",
            extra_fields={"conflict_strategy": "version", "auto_ingest": "false"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._assert_success_response(
            response,
            bundle_id=manifest["bundle"]["id"],
            file_count=1,
        )
