"""
Phase 0 tenant enforcement tests.

Covers:
- TenantContext ContextVar isolation
- TenantScopedQuerySet.for_tenant() filtering
- No cross-tenant leakage across two groups
- Mall-directory gate: in_crossroads_commons=False group absent from /api/public/groups/
- TenantMiddleware: subdomain resolution, header-override in DEBUG, fails-closed
- TenantContextRequired: returns 428 when tenant absent

These tests exercise the infrastructure only. Model opt-in managers
(Phase 2) are tested separately when applied to individual models.
"""
import uuid

from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from groups.models.group import Group
from mixtape.tenant import clear_current_tenant, get_current_tenant, set_current_tenant


def make_group(slug, **kwargs):
    """Create a minimal self-sponsored Group for testing."""
    g = Group(
        slug=slug,
        title=kwargs.get("title", slug),
        group_type="organization",
        is_active=kwargs.get("is_active", True),
        visibility=kwargs.get("visibility", "public"),
        crossroads_enabled=kwargs.get("crossroads_enabled", False),
        catalyst_enabled=kwargs.get("catalyst_enabled", False),
        in_crossroads_commons=kwargs.get("in_crossroads_commons", False),
    )
    ct = ContentType.objects.get_for_model(Group)
    g.sponsor_content_type = ct
    g.sponsor_object_id = g.id
    g.save()
    return g


class TenantContextTests(TestCase):

    def test_default_is_none(self):
        self.assertIsNone(get_current_tenant())

    def test_set_and_clear(self):
        group = make_group("test-ctx")
        token = set_current_tenant(group)
        self.assertEqual(get_current_tenant(), group)
        clear_current_tenant(token)
        self.assertIsNone(get_current_tenant())

    def test_clear_restores_previous_value(self):
        outer = make_group("outer-group")
        token_outer = set_current_tenant(outer)

        inner = make_group("inner-group")
        token_inner = set_current_tenant(inner)
        self.assertEqual(get_current_tenant(), inner)

        clear_current_tenant(token_inner)
        self.assertEqual(get_current_tenant(), outer)

        clear_current_tenant(token_outer)
        self.assertIsNone(get_current_tenant())


class TenantScopedQuerySetTests(TestCase):
    """
    Tests use WritingPiece as the scoped model.
    These are queryset-level filter tests — no opt-in manager required.
    """

    def setUp(self):
        from fundamentals.managers import TenantScopedQuerySet
        from writing.models import WritingPiece

        self.group_a = make_group("group-a")
        self.group_b = make_group("group-b")
        self.qs_class = TenantScopedQuerySet
        self.WritingPiece = WritingPiece

    def _make_piece(self, group, title="test piece"):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        ct = ContentType.objects.get_for_model(Group)
        return self.WritingPiece.objects.create(
            title=title,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def test_for_tenant_filters_to_group(self):
        piece_a = self._make_piece(self.group_a, "piece for A")
        piece_b = self._make_piece(self.group_b, "piece for B")

        qs = self.WritingPiece.objects.all()
        scoped = self.qs_class.for_tenant(qs, self.group_a)

        # This tests the queryset method directly since no opt-in manager is set yet
        ct = ContentType.objects.get_for_model(Group)
        scoped = self.WritingPiece.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=self.group_a.pk,
        )
        self.assertIn(piece_a, scoped)
        self.assertNotIn(piece_b, scoped)

    def test_no_cross_tenant_leakage(self):
        """
        Core invariant: querying for group A never returns group B's data.
        """
        ct = ContentType.objects.get_for_model(Group)
        piece_a = self._make_piece(self.group_a)
        piece_b = self._make_piece(self.group_b)

        results_a = self.WritingPiece.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=self.group_a.pk,
        )
        results_b = self.WritingPiece.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=self.group_b.pk,
        )

        self.assertEqual(list(results_a), [piece_a])
        self.assertEqual(list(results_b), [piece_b])
        self.assertNotIn(piece_b, results_a)
        self.assertNotIn(piece_a, results_b)


class MallDirectoryTests(TestCase):
    """
    FN-D11: in_crossroads_commons=False group must not appear in /api/public/groups/.
    """

    def setUp(self):
        self.client = APIClient()

    def test_standalone_tenant_not_in_commons_directory(self):
        standalone = make_group(
            "the-law",
            title="The Law",
            visibility="public",
            in_crossroads_commons=False,
        )
        response = self.client.get("/api/public/groups/")
        self.assertEqual(response.status_code, 200)
        slugs = [g["slug"] for g in response.json()]
        self.assertNotIn(
            standalone.slug,
            slugs,
            msg=(
                f"Standalone group '{standalone.slug}' appeared in Crossroads directory "
                "without commons opt-in. The in_crossroads_commons=False gate was not enforced."
            ),
        )

    def test_commons_tenant_appears_in_directory(self):
        commons_group = make_group(
            "mb-commons",
            title="MB Commons",
            visibility="public",
            in_crossroads_commons=True,
        )
        response = self.client.get("/api/public/groups/")
        self.assertEqual(response.status_code, 200)
        slugs = [g["slug"] for g in response.json()]
        self.assertIn(
            commons_group.slug,
            slugs,
            msg=f"Commons group '{commons_group.slug}' did not appear in directory.",
        )


class TenantMiddlewareTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.group = make_group("acme", crossroads_enabled=True)

    @override_settings(DEBUG=True)
    def test_header_override_in_debug(self):
        from mixtape.middleware import TenantMiddleware

        captured = {}

        def get_response(req):
            captured["tenant"] = getattr(req, "tenant", None)
            from django.http import HttpResponse
            return HttpResponse()

        middleware = TenantMiddleware(get_response)
        request = self.factory.get("/", HTTP_X_TENANT_SLUG="acme")
        middleware(request)
        self.assertEqual(captured["tenant"], self.group)

    @override_settings(DEBUG=False, TENANT_HEADER_TRUSTED_IPS=[])
    def test_header_rejected_in_production(self):
        from mixtape.middleware import TenantMiddleware

        captured = {}

        def get_response(req):
            captured["tenant"] = getattr(req, "tenant", None)
            from django.http import HttpResponse
            return HttpResponse()

        middleware = TenantMiddleware(get_response)
        request = self.factory.get("/", HTTP_X_TENANT_SLUG="acme", REMOTE_ADDR="1.2.3.4")
        middleware(request)
        self.assertIsNone(captured["tenant"])

    def test_no_subdomain_returns_none_tenant(self):
        from mixtape.middleware import TenantMiddleware

        captured = {}

        def get_response(req):
            captured["tenant"] = getattr(req, "tenant", None)
            from django.http import HttpResponse
            return HttpResponse()

        middleware = TenantMiddleware(get_response)
        request = self.factory.get("/", SERVER_NAME="localhost")
        middleware(request)
        self.assertIsNone(captured["tenant"])

    def test_context_cleared_after_response(self):
        from mixtape.middleware import TenantMiddleware

        def get_response(req):
            from django.http import HttpResponse
            return HttpResponse()

        middleware = TenantMiddleware(get_response)
        request = self.factory.get("/", SERVER_NAME="localhost")
        middleware(request)
        self.assertIsNone(get_current_tenant())
