import io
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from groups.models.group import Group, GroupType
from groups.models.membership import GroupMembership
from stackroom.models import Library, SourceFile, SourceFileVersion


User = get_user_model()


def _create_group(*, sponsor_user: User, title: str, slug: str) -> Group:
    group = Group(
        title=title,
        slug=slug,
        description="Test group",
        group_type=GroupType.COMMUNITY,
    )
    group.set_sponsor(sponsor_user)
    group.set_submitted_by(sponsor_user)
    group.author = sponsor_user
    group.author_name = sponsor_user.get_full_name() or sponsor_user.username
    group.save()
    return group


def _create_library(*, sponsor, submitted_by: User, title: str, is_personal: bool = False) -> Library:
    library = Library(
        title=title,
        is_personal_puddlejump=is_personal,
    )
    library.set_sponsor(sponsor)
    library.set_submitted_by(submitted_by)
    library.author = submitted_by
    library.author_name = submitted_by.get_full_name() or submitted_by.username
    library.save()
    return library


def _create_source_file(*, library: Library, created_by: User, suffix: str = "a") -> SourceFile:
    return SourceFile.objects.create(
        library=library,
        origin="upload",
        path=f"docs/{suffix}.md",
        filename=f"{suffix}.md",
        content_type="text/markdown",
        size_bytes=10,
        hash_sha256=f"{suffix:0<64}"[:64],
        created_by=created_by,
    )


class PuddlejumpSecurityFixesAPITests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="pj_owner",
            email="pj_owner@example.com",
            password="testpass123",
        )
        self.other = User.objects.create_user(
            username="pj_other",
            email="pj_other@example.com",
            password="testpass123",
        )
        self.member = User.objects.create_user(
            username="pj_member",
            email="pj_member@example.com",
            password="testpass123",
        )

        self.personal_library = _create_library(
            sponsor=self.owner,
            submitted_by=self.owner,
            title="Owner Personal Library",
            is_personal=True,
        )
        self.group = _create_group(
            sponsor_user=self.owner,
            title="Security Group",
            slug="security-group",
        )
        self.group_library = _create_library(
            sponsor=self.group,
            submitted_by=self.owner,
            title="Group Puddlejump",
        )

        user_ct = ContentType.objects.get_for_model(User)
        GroupMembership.objects.create(
            group=self.group,
            member_content_type=user_ct,
            member_object_id=self.owner.id,
            roles=["member", "owner"],
            is_active=True,
        )
        GroupMembership.objects.create(
            group=self.group,
            member_content_type=user_ct,
            member_object_id=self.member.id,
            roles=["member"],
            is_active=True,
        )

        self.personal_source = _create_source_file(
            library=self.personal_library,
            created_by=self.owner,
            suffix="personal",
        )
        self.personal_version = SourceFileVersion.objects.create(
            source_file=self.personal_source,
            version_number=1,
            hash_sha256="b" * 64,
            content_snapshot="# personal",
            actor=self.owner,
        )

        self.group_source = _create_source_file(
            library=self.group_library,
            created_by=self.owner,
            suffix="group",
        )
        self.group_version = SourceFileVersion.objects.create(
            source_file=self.group_source,
            version_number=1,
            hash_sha256="c" * 64,
            content_snapshot="# group",
            actor=self.owner,
        )

    def _auth_owner(self):
        self.client.force_authenticate(self.owner)

    def _auth_other(self):
        self.client.force_authenticate(self.other)

    def _auth_member(self):
        self.client.force_authenticate(self.member)

    # --- A. Canon view access control ---

    def test_versions_endpoint_owner_ok(self):
        self._auth_owner()
        response = self.client.get(f"/api/stackroom/source-files/{self.personal_source.id}/versions")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("versions", response.data)

    def test_versions_diff_checkout_checkin_other_user_gets_404(self):
        self._auth_other()
        for path in (
            f"/api/stackroom/source-files/{self.personal_source.id}/versions",
            f"/api/stackroom/source-files/{self.personal_source.id}/diff",
            f"/api/stackroom/source-files/{self.personal_source.id}/checkout",
            f"/api/stackroom/source-files/{self.personal_source.id}/checkin",
            f"/api/stackroom/libraries/{self.personal_library.id}/export",
            f"/api/stackroom/libraries/{self.personal_library.id}/status",
        ):
            with self.subTest(path=path):
                method = self.client.post if path.endswith("/checkin") else self.client.get
                response = method(path)
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_versions_unauthenticated_returns_401(self):
        response = self.client.get(f"/api/stackroom/source-files/{self.personal_source.id}/versions")
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    # --- B. Sync upload hardening ---

    def _sync_upload(self, *, path: str, content: bytes, name: str = "doc.md"):
        self._auth_owner()
        return self.client.post(
            "/api/stackroom/puddlejump/sync/upload",
            {"file": SimpleUploadedFile(name, content), "path": path},
            format="multipart",
        )

    def test_sync_upload_rejects_path_traversal(self):
        response = self._sync_upload(path="../../etc/passwd.md", content=b"# test")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("error"), "Invalid file path")

    def test_sync_upload_rejects_absolute_path(self):
        response = self._sync_upload(path="/etc/notes.md", content=b"# test")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("error"), "Invalid file path")

    def test_sync_upload_rejects_file_over_5mb(self):
        response = self._sync_upload(path="large.md", content=b"a" * ((5 * 1024 * 1024) + 1))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("maximum size of 5MB", response.data.get("error", ""))

    def test_sync_upload_rejects_non_markdown_extension(self):
        response = self._sync_upload(path="notes.txt", content=b"test", name="notes.txt")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(".md", response.data.get("error", ""))

    # --- C. Canon approval permissions ---

    def test_canon_approve_owner_succeeds(self):
        self._auth_owner()
        response = self.client.post(
            f"/api/stackroom/source-files/{self.personal_source.id}/approve",
            {"version_id": str(self.personal_version.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("is_canon"))

    def test_canon_approve_non_member_is_404(self):
        self._auth_other()
        response = self.client.post(
            f"/api/stackroom/source-files/{self.personal_source.id}/approve",
            {"version_id": str(self.personal_version.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_canon_approve_group_member_not_admin_is_403(self):
        self._auth_member()
        response = self.client.post(
            f"/api/stackroom/source-files/{self.group_source.id}/approve",
            {"version_id": str(self.group_version.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- D. Library status endpoint ---

    def test_library_status_owner_ok_and_warnings_shape(self):
        self._auth_owner()
        _create_source_file(library=self.personal_library, created_by=self.owner, suffix="status-2")
        self.personal_source.is_canon = True
        self.personal_source.save(update_fields=["is_canon", "updated_at"])

        response = self.client.get(f"/api/stackroom/libraries/{self.personal_library.id}/status")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["library_id"], str(self.personal_library.id))
        self.assertIn("bundle_id", response.data)
        self.assertIn("file_count", response.data)
        self.assertIn("canonical_count", response.data)
        self.assertIn("ingestion_status", response.data)
        self.assertIn("warnings", response.data)
        buckets = response.data["ingestion_status"]
        self.assertEqual(
            buckets["ready"] + buckets["processing"] + buckets["failed"] + buckets["pending"],
            response.data["file_count"],
        )

    def test_library_status_warn_approaching_limit(self):
        self._auth_owner()
        files = [
            SourceFile(
                library=self.personal_library,
                origin="upload",
                path=f"docs/bulk-{i}.md",
                filename=f"bulk-{i}.md",
                content_type="text/markdown",
                size_bytes=5,
                hash_sha256=f"{i:064x}"[-64:],
                created_by=self.owner,
            )
            for i in range(260)
        ]
        SourceFile.objects.bulk_create(files)

        response = self.client.get(f"/api/stackroom/libraries/{self.personal_library.id}/status")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = {warning["code"] for warning in response.data["warnings"]}
        self.assertIn("WARN_APPROACHING_LIMIT", codes)

    # --- E/F. Utility access + top_n bound ---

    @mock.patch("stackroom.api.puddlejump_utility_views.get_library_health")
    def test_group_library_health_member_access_and_non_member_denied(self, mock_health):
        mock_health.return_value = {
            "library_id": str(self.group_library.id),
            "file_count": 0,
            "total_size_bytes": 0,
            "folder_depth": 0,
            "canon_coverage": {"total_items": 0, "canonical_items": 0, "percentage": 0},
            "summary_coverage": {"total_artifacts": 0, "with_summary": 0, "percentage": 0},
            "keyword_coverage": {"total_artifacts": 0, "with_keywords": 0, "percentage": 0},
            "missing_summaries": [],
            "overdue_reviews": [],
            "ingestion_status": {
                "total_source_files": 0,
                "fully_embedded": 0,
                "pending_embedding": 0,
                "failed_embedding": 0,
                "percentage_complete": 0,
            },
        }

        self._auth_member()
        ok = self.client.get(f"/api/stackroom/puddlejump/utilities/libraries/{self.group_library.id}/health")
        self.assertEqual(ok.status_code, status.HTTP_200_OK)

        self._auth_other()
        denied = self.client.get(f"/api/stackroom/puddlejump/utilities/libraries/{self.group_library.id}/health")
        self.assertEqual(denied.status_code, status.HTTP_404_NOT_FOUND)

    @mock.patch("stackroom.api.puddlejump_utility_views.suggest_canonical_candidates", return_value=[])
    def test_suggest_canonical_top_n_bounds(self, _mock_suggest):
        self._auth_owner()
        too_large = self.client.post(
            "/api/stackroom/puddlejump/utilities/suggest-canonical",
            {"library_id": str(self.personal_library.id), "top_n": 500},
            format="json",
        )
        self.assertEqual(too_large.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("between 1 and 100", too_large.data.get("error", ""))

        at_limit = self.client.post(
            "/api/stackroom/puddlejump/utilities/suggest-canonical",
            {"library_id": str(self.personal_library.id), "top_n": 100},
            format="json",
        )
        self.assertEqual(at_limit.status_code, status.HTTP_200_OK)
        self.assertEqual(at_limit.data["top_n"], 100)

    def test_export_includes_bundle_id_header(self):
        self._auth_owner()
        response = self.client.get(f"/api/stackroom/libraries/{self.personal_library.id}/export")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.has_header("X-Bundle-Id"))

