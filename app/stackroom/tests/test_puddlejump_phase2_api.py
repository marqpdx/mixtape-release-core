# stackroom/tests/test_puddlejump_phase2_api.py

import io
import json
import zipfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from stackroom.models import Library, LibraryItem


User = get_user_model()


def _make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for path, content in files.items():
            zip_file.writestr(path, content)
    return buffer.getvalue()


def _manifest_payload(*, bundle_id: str, title: str, files: list[dict]) -> dict:
    return {
        "format_version": "1.0.0",
        "bundle": {
            "id": bundle_id,
            "title": title,
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


def _upload(client, file_bytes: bytes, name: str):
    return client.post(
        "/api/stackroom/puddlejump/import/",
        data={"file": SimpleUploadedFile(name, file_bytes)},
        format="multipart",
    )


class PuddlejumpPhase2ImportTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="puddlejump-phase2",
            email="puddlejump-phase2@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=self.user)

    def test_import_minimal_bundle_creates_library_and_item(self):
        bundle_id = "550e8400-e29b-41d4-a716-446655440000"
        manifest = _manifest_payload(
            bundle_id=bundle_id,
            title="Test Bundle",
            files=[{"path": "test.md", "hash": "sha256:abc", "size_bytes": 10}],
        )
        bundle = _make_zip({
            "puddlejump.json": json.dumps(manifest).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/test.md": b"# Test",
        })

        response = _upload(self.client, bundle, "test-valid-minimal.zip")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("library_id", response.data)
        self.assertIn("library_slug", response.data)
        self.assertEqual(response.data["bundle_id"], bundle_id)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["counts"]["new_files"], 1)

        library = Library.objects.filter(title="Test Bundle").first()
        self.assertIsNotNone(library)
        self.assertTrue(hasattr(library, "puddlejump_bundle_id"))
        self.assertEqual(library.puddlejump_bundle_id, bundle_id)
        self.assertEqual(library.puddlejump_origin, "imported")

        items = LibraryItem.objects.filter(library=library)
        self.assertEqual(items.count(), 1)
        self.assertFalse(items.first().is_folder)

    def test_import_multi_file_bundle_creates_folders(self):
        bundle_id = "650e8400-e29b-41d4-a716-446655440001"
        manifest = _manifest_payload(
            bundle_id=bundle_id,
            title="Multi File Test",
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

        response = _upload(self.client, bundle, "test-valid-multi.zip")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["counts"]["new_files"], 3)

        library = Library.objects.filter(title="Multi File Test").first()
        self.assertIsNotNone(library)

        items = LibraryItem.objects.filter(library=library)
        self.assertEqual(items.count(), 5)
        self.assertEqual(items.filter(is_folder=True).count(), 2)
        self.assertEqual(items.filter(is_folder=False).count(), 3)

    def test_canonical_metadata_is_stored(self):
        bundle_id = "750e8400-e29b-41d4-a716-446655440002"
        manifest = _manifest_payload(
            bundle_id=bundle_id,
            title="Canonical Test",
            files=[
                {"path": "canonical.md", "hash": "sha256:111", "size_bytes": 10, "canonical": True},
                {"path": "non-canonical.md", "hash": "sha256:222", "size_bytes": 10, "canonical": False},
            ],
        )
        canonical_md = b"""---\ncanonical: true\ncanonical_date: "2026-01-12"\ncanonical_authority: "Engineering Team"\nsupersedes: "old-spec.md"\nreview_date: "2027-01-12"\ntags: [spec, api, canonical]\nsummary: "This is the authoritative API specification"\n---\n# Canonical\n"""
        non_canonical_md = b"""---\ncanonical: false\ntags: [draft]\n---\n# Draft\n"""
        bundle = _make_zip({
            "puddlejump.json": json.dumps(manifest).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/canonical.md": canonical_md,
            "Documents/non-canonical.md": non_canonical_md,
        })

        response = _upload(self.client, bundle, "test-canonical.zip")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        library = Library.objects.filter(title="Canonical Test").first()
        self.assertIsNotNone(library)

        canonical_item = LibraryItem.objects.filter(
            library=library,
            folder_path="canonical.md",
        ).first()
        self.assertIsNotNone(canonical_item)
        self.assertTrue(hasattr(canonical_item, "puddlejump_canonical_metadata"))
        self.assertTrue(canonical_item.is_featured)
        self.assertEqual(
            canonical_item.puddlejump_canonical_metadata.get("canonical_authority"),
            "Engineering Team",
        )
        self.assertIn("canonical", canonical_item.tags)
        self.assertEqual(
            canonical_item.notes,
            "This is the authoritative API specification",
        )

        non_canonical_item = LibraryItem.objects.filter(
            library=library,
            folder_path="non-canonical.md",
        ).first()
        self.assertIsNotNone(non_canonical_item)
        self.assertFalse(non_canonical_item.is_featured)

    def test_reimport_same_bundle_reuses_library(self):
        bundle_id = "550e8400-e29b-41d4-a716-446655440000"
        manifest = _manifest_payload(
            bundle_id=bundle_id,
            title="Test Bundle",
            files=[{"path": "test.md", "hash": "sha256:abc", "size_bytes": 10}],
        )
        bundle = _make_zip({
            "puddlejump.json": json.dumps(manifest).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/test.md": b"# Test",
        })

        first = _upload(self.client, bundle, "test-valid-minimal.zip")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        first_id = first.data["library_id"]

        second = _upload(self.client, bundle, "test-valid-minimal.zip")
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["library_id"], first_id)
        self.assertEqual(
            Library.objects.filter(puddlejump_bundle_id=bundle_id).count(),
            1,
        )

    def test_multiple_bundles_create_separate_libraries(self):
        manifest_one = _manifest_payload(
            bundle_id="550e8400-e29b-41d4-a716-446655440000",
            title="Test Bundle",
            files=[{"path": "test.md", "hash": "sha256:abc", "size_bytes": 10}],
        )
        manifest_two = _manifest_payload(
            bundle_id="650e8400-e29b-41d4-a716-446655440001",
            title="Multi File Test",
            files=[{"path": "guides/onboarding.md", "hash": "sha256:111", "size_bytes": 10}],
        )
        bundle_one = _make_zip({
            "puddlejump.json": json.dumps(manifest_one).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/test.md": b"# Test",
        })
        bundle_two = _make_zip({
            "puddlejump.json": json.dumps(manifest_two).encode("utf-8"),
            "PUDDLEJUMP.md": b"# Catalog",
            "Documents/guides/onboarding.md": b"# Onboarding",
        })

        first = _upload(self.client, bundle_one, "test-valid-minimal.zip")
        second = _upload(self.client, bundle_two, "test-valid-multi.zip")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertNotEqual(first.data["library_id"], second.data["library_id"])
        self.assertEqual(
            Library.objects.filter(
                title__in=["Test Bundle", "Multi File Test"]
            ).count(),
            2,
        )
