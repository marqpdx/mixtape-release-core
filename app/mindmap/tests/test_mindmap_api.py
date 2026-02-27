from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from mindmap.models import MindMap, MindMapEdge, MindMapNode, MindMapNodeAttachment
from mindmap.services import mindmap_service
from writing.models import Leaf


User = get_user_model()


class MindMapAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="mind_owner",
            email="mind_owner@example.com",
            password="testpass123",
        )
        self.other = User.objects.create_user(
            username="mind_other",
            email="mind_other@example.com",
            password="testpass123",
        )
        self.owner_map = mindmap_service.create_mindmap(
            sponsor=self.owner,
            title="Owner Map",
            author=self.owner,
            submitted_by=self.owner,
        )
        self.other_map = mindmap_service.create_mindmap(
            sponsor=self.other,
            title="Other Map",
            author=self.other,
            submitted_by=self.other,
        )

    def _auth_owner(self):
        self.client.force_authenticate(self.owner)

    def _auth_other(self):
        self.client.force_authenticate(self.other)

    def _map_url(self, mindmap):
        return f"/api/mindmaps/{mindmap.id}/"

    def _nodes_url(self, mindmap):
        return f"/api/mindmaps/{mindmap.id}/nodes/"

    def _node_url(self, mindmap, node):
        return f"/api/mindmaps/{mindmap.id}/nodes/{node.id}/"

    def _edges_url(self, mindmap):
        return f"/api/mindmaps/{mindmap.id}/edges/"

    def _edge_url(self, mindmap, edge):
        return f"/api/mindmaps/{mindmap.id}/edges/{edge.id}/"

    def _attachments_url(self, mindmap, node):
        return f"/api/mindmaps/{mindmap.id}/nodes/{node.id}/attachments/"

    def _attachment_url(self, mindmap, node, attachment):
        return f"/api/mindmaps/{mindmap.id}/nodes/{node.id}/attachments/{attachment.id}/"

    def _create_node(self, mindmap=None, **overrides):
        if mindmap is None:
            mindmap = self.owner_map
        data = {
            "node_type": "note",
            "pos_x": 10,
            "pos_y": 20,
            "title": "Node title",
            "text": "Body",
            "backing_kind": "inline",
            "meta": {},
        }
        data.update(overrides)
        return MindMapNode.objects.create(mind_map=mindmap, **data)

    def _create_edge(self, source, target, mindmap=None, **overrides):
        if mindmap is None:
            mindmap = self.owner_map
        data = {
            "edge_type": "related",
            "label": "rel",
            "directed": True,
            "style": {},
            "meta": {},
        }
        data.update(overrides)
        return MindMapEdge.objects.create(
            mind_map=mindmap, source_node=source, target_node=target, **data
        )

    # --- A. MindMap CRUD ---

    def test_create_mindmap(self):
        self._auth_owner()
        response = self.client.post("/api/mindmaps/", {"title": "Fresh Map"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Fresh Map")
        self.assertIn("id", response.data)
        self.assertEqual(response.data["version"], 0)

    def test_create_mindmap_default_status_draft(self):
        self._auth_owner()
        response = self.client.post("/api/mindmaps/", {"title": "Drafty"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "draft")

    def test_create_mindmap_slug_generated_from_title(self):
        self._auth_owner()
        response = self.client.post("/api/mindmaps/", {"title": "My Slug Test"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["slug"], "my-slug-test")

    def test_list_mindmaps_only_own(self):
        self._auth_owner()
        response = self.client.get("/api/mindmaps/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data}
        self.assertIn(str(self.owner_map.id), ids)
        self.assertNotIn(str(self.other_map.id), ids)

    def test_list_excludes_deleted(self):
        self._auth_owner()
        self.owner_map.deleted_at = timezone.now()
        self.owner_map.save(update_fields=["deleted_at", "updated_at"])
        response = self.client.get("/api/mindmaps/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data}
        self.assertNotIn(str(self.owner_map.id), ids)

    def test_get_mindmap_detail_with_counts(self):
        self._auth_owner()
        n1 = self._create_node()
        n2 = self._create_node(title="Node 2")
        self._create_edge(n1, n2)
        response = self.client.get(self._map_url(self.owner_map))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["node_count"], 2)
        self.assertEqual(response.data["edge_count"], 1)
        self.assertIn("viewport", response.data)

    def test_get_mindmap_detail_counts_exclude_deleted(self):
        self._auth_owner()
        n1 = self._create_node()
        n2 = self._create_node(title="Node 2")
        edge = self._create_edge(n1, n2)
        n2.deleted_at = timezone.now()
        n2.save(update_fields=["deleted_at", "updated_at"])
        edge.deleted_at = timezone.now()
        edge.save(update_fields=["deleted_at", "updated_at"])
        response = self.client.get(self._map_url(self.owner_map))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["node_count"], 1)
        self.assertEqual(response.data["edge_count"], 0)

    def test_patch_mindmap_title(self):
        self._auth_owner()
        response = self.client.patch(self._map_url(self.owner_map), {"title": "Renamed Map"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.title, "Renamed Map")

    def test_patch_mindmap_viewport_no_version_bump(self):
        self._auth_owner()
        before = self.owner_map.version
        response = self.client.patch(
            self._map_url(self.owner_map),
            {"viewport": {"x": 10, "y": 20, "zoom": 1.1}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before)

    def test_patch_mindmap_status(self):
        self._auth_owner()
        response = self.client.patch(self._map_url(self.owner_map), {"status": "review"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.status, "review")

    def test_create_mindmap_unauthenticated(self):
        response = self.client.post("/api/mindmaps/", {"title": "Nope"}, format="json")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_get_other_users_mindmap_denied(self):
        self._auth_owner()
        response = self.client.get(self._map_url(self.other_map))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- B/C. Node CRUD + Bulk ---

    def test_create_node_and_version_bump(self):
        self._auth_owner()
        before = self.owner_map.version
        response = self.client.post(
            self._nodes_url(self.owner_map),
            {
                "node_type": "note",
                "pos_x": 1,
                "pos_y": 2,
                "backing_kind": "inline",
                "title": "N1",
                "text": "Body",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before + 1)
        self.assertEqual(response.data["title"], "N1")

    def test_create_leaf_backed_node(self):
        self._auth_owner()
        leaf = Leaf.objects.create(author=self.owner, body_text="Leaf body", kind="text")
        response = self.client.post(
            self._nodes_url(self.owner_map),
            {
                "node_type": "leaf",
                "pos_x": 1,
                "pos_y": 2,
                "backing_kind": "leaf",
                "leaf": str(leaf.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["backing_kind"], "leaf")
        self.assertEqual(str(response.data["leaf"]), str(leaf.id))

    def test_list_nodes_excludes_deleted(self):
        self._auth_owner()
        alive = self._create_node(title="alive")
        deleted = self._create_node(title="deleted")
        deleted.deleted_at = timezone.now()
        deleted.save(update_fields=["deleted_at", "updated_at"])
        response = self.client.get(self._nodes_url(self.owner_map))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {str(row["id"]) for row in response.data}
        self.assertIn(str(alive.id), ids)
        self.assertNotIn(str(deleted.id), ids)

    def test_patch_node_position_no_version_bump(self):
        self._auth_owner()
        node = self._create_node()
        before = self.owner_map.version
        response = self.client.patch(
            self._node_url(self.owner_map, node), {"pos_x": 99, "pos_y": 101}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before)

    def test_patch_node_title_bumps_version(self):
        self._auth_owner()
        node = self._create_node()
        before = self.owner_map.version
        response = self.client.patch(
            self._node_url(self.owner_map, node), {"title": "Changed"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before + 1)

    def test_delete_node_cascades_to_edges(self):
        self._auth_owner()
        n1 = self._create_node()
        n2 = self._create_node(title="n2")
        edge = self._create_edge(n1, n2)
        response = self.client.delete(self._node_url(self.owner_map, n1))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        edge.refresh_from_db()
        self.assertIsNotNone(edge.deleted_at)

    def test_node_wrong_mindmap_404(self):
        self._auth_owner()
        node = self._create_node(mindmap=self.owner_map)
        response = self.client.patch(
            self._node_url(self.other_map, node), {"title": "Nope"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bulk_upsert_create_and_update_nodes(self):
        self._auth_owner()
        node = self._create_node(title="before")
        before = self.owner_map.version
        response = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/nodes/bulk_upsert/",
            {
                "items": [
                    {"id": str(node.id), "title": "after"},
                    {"node_type": "note", "pos_x": 50, "pos_y": 60, "title": "created"},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["ok"])
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before + 1)
        node.refresh_from_db()
        self.assertEqual(node.title, "after")

    def test_bulk_upsert_position_only_no_version_bump(self):
        self._auth_owner()
        node = self._create_node()
        before = self.owner_map.version
        response = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/nodes/bulk_upsert/",
            {"items": [{"id": str(node.id), "pos_x": 200, "pos_y": 300}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before)

    def test_bulk_upsert_not_found_returns_error(self):
        self._auth_owner()
        response = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/nodes/bulk_upsert/",
            {"items": [{"id": 999999, "title": "missing"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["results"][0]["ok"])

    def test_bulk_upsert_empty_items_rejected(self):
        self._auth_owner()
        response = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/nodes/bulk_upsert/", {"items": []}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_delete_nodes_and_version(self):
        self._auth_owner()
        node = self._create_node()
        before = self.owner_map.version
        response = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/nodes/bulk_delete/",
            {"ids": [str(node.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deleted"], 1)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before + 1)

    def test_bulk_delete_empty_ids_rejected(self):
        self._auth_owner()
        response = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/nodes/bulk_delete/", {"ids": []}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- D/E. Edge CRUD + Bulk ---

    def test_create_edge_and_version_bump(self):
        self._auth_owner()
        s = self._create_node(title="s")
        t = self._create_node(title="t")
        before = self.owner_map.version
        response = self.client.post(
            self._edges_url(self.owner_map),
            {
                "source_node": str(s.id),
                "target_node": str(t.id),
                "edge_type": "depends_on",
                "label": "Edge label",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["edge_type"], "depends_on")
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before + 1)

    def test_create_edge_validates_nodes_in_mindmap(self):
        self._auth_owner()
        own = self._create_node(mindmap=self.owner_map)
        foreign = self._create_node(mindmap=self.other_map)
        response = self.client.post(
            self._edges_url(self.owner_map),
            {
                "source_node": str(own.id),
                "target_node": str(foreign.id),
                "edge_type": "related",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("target_node", response.data)

    def test_patch_edge_style_no_version_bump(self):
        self._auth_owner()
        s = self._create_node(title="s")
        t = self._create_node(title="t")
        edge = self._create_edge(s, t)
        before = self.owner_map.version
        response = self.client.patch(
            self._edge_url(self.owner_map, edge), {"style": {"color": "red"}}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before)

    def test_patch_edge_label_bumps_version(self):
        self._auth_owner()
        s = self._create_node(title="s")
        t = self._create_node(title="t")
        edge = self._create_edge(s, t)
        before = self.owner_map.version
        response = self.client.patch(
            self._edge_url(self.owner_map, edge), {"label": "changed"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before + 1)

    def test_delete_edge_soft_deletes_and_bumps_version(self):
        self._auth_owner()
        s = self._create_node(title="s")
        t = self._create_node(title="t")
        edge = self._create_edge(s, t)
        before = self.owner_map.version
        response = self.client.delete(self._edge_url(self.owner_map, edge))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        edge.refresh_from_db()
        self.assertIsNotNone(edge.deleted_at)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before + 1)

    def test_bulk_upsert_edges_and_bulk_delete_edges(self):
        self._auth_owner()
        s = self._create_node(title="s")
        t = self._create_node(title="t")
        create_response = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/edges/bulk_upsert/",
            {"items": [{"source_node": str(s.id), "target_node": str(t.id), "edge_type": "supports"}]},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_200_OK)
        edge_id = create_response.data["results"][0]["id"]

        update_response = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/edges/bulk_upsert/",
            {"items": [{"id": edge_id, "label": "updated"}]},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        delete_response = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/edges/bulk_delete/",
            {"ids": [edge_id]},
            format="json",
        )
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK)
        self.assertEqual(delete_response.data["deleted"], 1)

    def test_bulk_edge_empty_payloads_rejected(self):
        self._auth_owner()
        upsert = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/edges/bulk_upsert/", {"items": []}, format="json"
        )
        self.assertEqual(upsert.status_code, status.HTTP_400_BAD_REQUEST)
        delete = self.client.post(
            f"/api/mindmaps/{self.owner_map.id}/edges/bulk_delete/", {"ids": []}, format="json"
        )
        self.assertEqual(delete.status_code, status.HTTP_400_BAD_REQUEST)

    # --- F. Attachment CRUD ---

    def test_attachment_create_patch_delete(self):
        self._auth_owner()
        node = self._create_node()
        before = self.owner_map.version
        create_response = self.client.post(
            self._attachments_url(self.owner_map, node),
            {
                "kind": "url",
                "title": "Reference",
                "url": "https://example.com/ref",
                "meta": {},
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.owner_map.refresh_from_db()
        self.assertEqual(self.owner_map.version, before + 1)

        attachment_id = create_response.data["id"]
        attachment = MindMapNodeAttachment.objects.get(pk=attachment_id)
        patch_response = self.client.patch(
            self._attachment_url(self.owner_map, node, attachment),
            {"title": "Updated ref"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        delete_response = self.client.delete(self._attachment_url(self.owner_map, node, attachment))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        attachment.refresh_from_db()
        self.assertIsNotNone(attachment.deleted_at)

    def test_attachment_list_excludes_deleted(self):
        self._auth_owner()
        node = self._create_node()
        alive = MindMapNodeAttachment.objects.create(node=node, kind="url", title="A")
        dead = MindMapNodeAttachment.objects.create(node=node, kind="url", title="B")
        dead.deleted_at = timezone.now()
        dead.save(update_fields=["deleted_at", "updated_at"])
        response = self.client.get(self._attachments_url(self.owner_map, node))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {str(row["id"]) for row in response.data}
        self.assertIn(str(alive.id), ids)
        self.assertNotIn(str(dead.id), ids)

    # --- G/H/I. Version, permissions, and soft-delete integrity ---

    def test_version_atomic_increment(self):
        self._auth_owner()
        v0 = self.owner_map.version
        v1 = mindmap_service.bump_version(self.owner_map)
        v2 = mindmap_service.bump_version(self.owner_map)
        self.assertEqual(v1, v0 + 1)
        self.assertEqual(v2, v0 + 2)

    def test_other_user_mindmap_list_empty(self):
        self._auth_other()
        response = self.client.get("/api/mindmaps/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data}
        self.assertNotIn(str(self.owner_map.id), ids)

    def test_other_user_node_edge_attachment_ops_forbidden(self):
        self._auth_owner()
        node_a = self._create_node()
        node_b = self._create_node(title="b")
        edge = self._create_edge(node_a, node_b)
        att = MindMapNodeAttachment.objects.create(node=node_a, kind="url", title="X")

        self._auth_other()
        node_post = self.client.post(
            self._nodes_url(self.owner_map), {"node_type": "note", "pos_x": 1, "pos_y": 2}, format="json"
        )
        edge_post = self.client.post(
            self._edges_url(self.owner_map),
            {"source_node": str(node_a.id), "target_node": str(node_b.id), "edge_type": "related"},
            format="json",
        )
        att_patch = self.client.patch(
            self._attachment_url(self.owner_map, node_a, att), {"title": "Nope"}, format="json"
        )
        edge_delete = self.client.delete(self._edge_url(self.owner_map, edge))

        self.assertEqual(node_post.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(edge_post.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(att_patch.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(edge_delete.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_all_endpoints_401(self):
        node = self._create_node()
        edge = self._create_edge(node, self._create_node(title="t2"))
        att = MindMapNodeAttachment.objects.create(node=node, kind="url", title="T")

        endpoints = [
            ("get", "/api/mindmaps/", None),
            ("post", "/api/mindmaps/", {"title": "x"}),
            ("get", self._map_url(self.owner_map), None),
            ("patch", self._map_url(self.owner_map), {"title": "x"}),
            ("get", self._nodes_url(self.owner_map), None),
            ("post", self._nodes_url(self.owner_map), {"node_type": "note", "pos_x": 1, "pos_y": 1}),
            ("patch", self._node_url(self.owner_map, node), {"title": "x"}),
            ("delete", self._node_url(self.owner_map, node), None),
            ("post", f"/api/mindmaps/{self.owner_map.id}/nodes/bulk_upsert/", {"items": [{"node_type": "note", "pos_x": 1, "pos_y": 1}]}),
            ("post", f"/api/mindmaps/{self.owner_map.id}/nodes/bulk_delete/", {"ids": [str(node.id)]}),
            ("get", self._edges_url(self.owner_map), None),
            ("post", self._edges_url(self.owner_map), {"source_node": str(node.id), "target_node": str(node.id), "edge_type": "r"}),
            ("patch", self._edge_url(self.owner_map, edge), {"label": "x"}),
            ("delete", self._edge_url(self.owner_map, edge), None),
            ("post", f"/api/mindmaps/{self.owner_map.id}/edges/bulk_upsert/", {"items": [{"source_node": str(node.id), "target_node": str(node.id), "edge_type": "r"}]}),
            ("post", f"/api/mindmaps/{self.owner_map.id}/edges/bulk_delete/", {"ids": [str(edge.id)]}),
            ("get", self._attachments_url(self.owner_map, node), None),
            ("post", self._attachments_url(self.owner_map, node), {"kind": "url", "title": "x"}),
            ("patch", self._attachment_url(self.owner_map, node, att), {"title": "x"}),
            ("delete", self._attachment_url(self.owner_map, node, att), None),
        ]

        for method, url, payload in endpoints:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, payload, format="json")
                self.assertIn(
                    response.status_code,
                    (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
                )

    def test_delete_node_cascade_edge_integrity(self):
        self._auth_owner()
        a = self._create_node(title="a")
        b = self._create_node(title="b")
        c = self._create_node(title="c")
        e1 = self._create_edge(a, b)
        e2 = self._create_edge(b, c)
        self.client.delete(self._node_url(self.owner_map, b))
        e1.refresh_from_db()
        e2.refresh_from_db()
        self.assertIsNotNone(e1.deleted_at)
        self.assertIsNotNone(e2.deleted_at)
