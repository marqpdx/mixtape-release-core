from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from lists.models import List
from lists.parser import (
    ItemType,
    count_items,
    parse_list_text,
    reorder_items,
    serialize_list_items,
    toggle_item_completion,
)

User = get_user_model()


class ListModelTests(TestCase):
    """Tests for the List model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.user_ct = ContentType.objects.get_for_model(User)

    def test_create_list(self):
        """Test creating a basic list."""
        lst = List.objects.create(
            title="My Todo List",
            body_text="- first item\n- second item",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )
        self.assertEqual(lst.title, "My Todo List")
        self.assertIn("first item", lst.body_text)
        self.assertIsNotNone(lst.slug)

    def test_sponsor_scoped_slug_uniqueness(self):
        """Test that different sponsors can have lists with the same slug."""
        user2 = User.objects.create_user(
            username="testuser2",
            email="test2@example.com",
            password="testpass123",
        )

        # Create list for user 1
        list1 = List.objects.create(
            title="Shopping",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        # Create list with same title for user 2
        list2 = List.objects.create(
            title="Shopping",
            submitted_by=user2,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=user2.id,
        )

        # Both should have the same slug since they have different sponsors
        self.assertEqual(list1.slug, list2.slug)

    def test_same_sponsor_unique_slug(self):
        """Test that same sponsor gets unique slugs for same title."""
        list1 = List.objects.create(
            title="Todo",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )
        list2 = List.objects.create(
            title="Todo",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        # Should have different slugs (todo, todo-2, etc.)
        self.assertNotEqual(list1.slug, list2.slug)


class ListAPITests(TestCase):
    """Tests for the List API endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.user_ct = ContentType.objects.get_for_model(User)
        self.client.force_authenticate(user=self.user)

    def test_create_list(self):
        """Test creating a list via API."""
        response = self.client.post(
            "/api/lists/",
            {"title": "New List", "body_text": "- item one"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["title"], "New List")

    def test_list_lists(self):
        """Test listing user's lists."""
        List.objects.create(
            title="List 1",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )
        List.objects.create(
            title="List 2",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        response = self.client.get("/api/lists/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    def test_get_list_by_id(self):
        """Test retrieving a specific list."""
        lst = List.objects.create(
            title="My List",
            body_text="- item",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        response = self.client.get(f"/api/lists/{lst.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["title"], "My List")

    def test_update_list(self):
        """Test updating a list's body_text."""
        lst = List.objects.create(
            title="My List",
            body_text="- old item",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        response = self.client.patch(
            f"/api/lists/{lst.id}/",
            {"body_text": "- new item\nx done item"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("new item", response.data["body_text"])

    def test_search_lists(self):
        """Test searching lists by title."""
        List.objects.create(
            title="Shopping List",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )
        List.objects.create(
            title="Work Tasks",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        response = self.client.get("/api/lists/search/", {"q": "shop"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "Shopping List")

    def test_get_by_slug(self):
        """Test retrieving a list by slug."""
        lst = List.objects.create(
            title="Weekly Review",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        response = self.client.get(f"/api/lists/by-slug/{lst.slug}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["title"], "Weekly Review")

    def test_toggle_item(self):
        """Test toggling an item's completion status."""
        lst = List.objects.create(
            title="Todo",
            body_text="- first item\n- second item",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        # Toggle first item (index 0)
        response = self.client.post(f"/api/lists/{lst.id}/items/0/toggle")
        self.assertEqual(response.status_code, 200)
        self.assertIn("x first item", response.data["body_text"])

        # Toggle again to uncomplete
        response = self.client.post(f"/api/lists/{lst.id}/items/0/toggle")
        self.assertEqual(response.status_code, 200)
        self.assertIn("- first item", response.data["body_text"])

    def test_reorder_items(self):
        """Test reordering items."""
        lst = List.objects.create(
            title="Todo",
            body_text="- first\n- second\n- third",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        # Move first item to end
        response = self.client.post(
            f"/api/lists/{lst.id}/reorder",
            {"from_index": 0, "to_index": 3},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["body_text"], "- second\n- third\n- first")

    def test_list_includes_parsed_items(self):
        """Test that list response includes parsed items."""
        lst = List.objects.create(
            title="Todo",
            body_text="- open item\nx done item\n* note item",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        response = self.client.get(f"/api/lists/{lst.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("items", response.data)
        self.assertEqual(len(response.data["items"]), 3)
        self.assertEqual(response.data["items"][0]["type"], "action_open")
        self.assertEqual(response.data["items"][1]["type"], "action_done")
        self.assertEqual(response.data["items"][2]["type"], "note")

    def test_list_includes_stats(self):
        """Test that list response includes stats."""
        lst = List.objects.create(
            title="Todo",
            body_text="- open item\nx done item\n* note item",
            submitted_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

        response = self.client.get(f"/api/lists/{lst.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("stats", response.data)
        self.assertEqual(response.data["stats"]["total"], 3)
        self.assertEqual(response.data["stats"]["open"], 1)
        self.assertEqual(response.data["stats"]["done"], 1)
        self.assertEqual(response.data["stats"]["notes"], 1)


class ParserTests(TestCase):
    """Tests for the list grammar parser."""

    def test_parse_empty(self):
        """Test parsing empty text."""
        items = parse_list_text("")
        self.assertEqual(items, [])

    def test_parse_open_items(self):
        """Test parsing open action items."""
        text = "- first\n- second"
        items = parse_list_text(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].item_type, ItemType.ACTION_OPEN)
        self.assertEqual(items[0].text, "first")
        self.assertEqual(items[1].text, "second")

    def test_parse_done_items(self):
        """Test parsing completed action items."""
        text = "x done task"
        items = parse_list_text(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, ItemType.ACTION_DONE)
        self.assertEqual(items[0].text, "done task")

    def test_parse_note_items(self):
        """Test parsing note items."""
        text = "* this is a note"
        items = parse_list_text(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, ItemType.NOTE)
        self.assertEqual(items[0].text, "this is a note")

    def test_parse_mixed_items(self):
        """Test parsing mixed item types."""
        text = "- open\nx done\n* note"
        items = parse_list_text(text)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].item_type, ItemType.ACTION_OPEN)
        self.assertEqual(items[1].item_type, ItemType.ACTION_DONE)
        self.assertEqual(items[2].item_type, ItemType.NOTE)

    def test_parse_sub_items(self):
        """Test parsing sub-items."""
        text = "- parent\n  - child 1\n  - child 2"
        items = parse_list_text(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(items[0].children), 2)
        self.assertEqual(items[0].children[0].text, "child 1")
        self.assertEqual(items[0].children[0].parent_index, 0)

    def test_parse_mixed_sub_items(self):
        """Test parsing sub-items with different types."""
        text = "- parent\n  x done child\n  * note child"
        items = parse_list_text(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(items[0].children), 2)
        self.assertEqual(items[0].children[0].item_type, ItemType.ACTION_DONE)
        self.assertEqual(items[0].children[1].item_type, ItemType.NOTE)

    def test_serialize_items(self):
        """Test serializing items back to text."""
        text = "- first\nx second\n* third"
        items = parse_list_text(text)
        result = serialize_list_items(items)
        self.assertEqual(result, text)

    def test_serialize_with_children(self):
        """Test serializing items with children."""
        text = "- parent\n  - child"
        items = parse_list_text(text)
        result = serialize_list_items(items)
        self.assertEqual(result, text)

    def test_toggle_open_to_done(self):
        """Test toggling open item to done."""
        items = parse_list_text("- task")
        items = toggle_item_completion(items, 0)
        self.assertEqual(items[0].item_type, ItemType.ACTION_DONE)

    def test_toggle_done_to_open(self):
        """Test toggling done item to open."""
        items = parse_list_text("x task")
        items = toggle_item_completion(items, 0)
        self.assertEqual(items[0].item_type, ItemType.ACTION_OPEN)

    def test_toggle_note_raises(self):
        """Test that toggling note raises error."""
        items = parse_list_text("* note")
        with self.assertRaises(ValueError):
            toggle_item_completion(items, 0)

    def test_toggle_child_item(self):
        """Test toggling a child item."""
        items = parse_list_text("- parent\n  - child")
        items = toggle_item_completion(items, 1)  # child has index 1
        self.assertEqual(items[0].children[0].item_type, ItemType.ACTION_DONE)

    def test_reorder_items(self):
        """Test reordering items."""
        items = parse_list_text("- first\n- second\n- third")
        items = reorder_items(items, 0, 3)
        texts = [item.text for item in items]
        self.assertEqual(texts, ["second", "third", "first"])

    def test_reorder_with_children(self):
        """Test that children move with parent."""
        items = parse_list_text("- parent\n  - child\n- other")
        items = reorder_items(items, 0, 2)
        self.assertEqual(items[0].text, "other")
        self.assertEqual(items[1].text, "parent")
        self.assertEqual(len(items[1].children), 1)

    def test_count_items(self):
        """Test counting items."""
        items = parse_list_text("- open\nx done\n* note\n  - child open")
        stats = count_items(items)
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["open"], 2)
        self.assertEqual(stats["done"], 1)
        self.assertEqual(stats["notes"], 1)


class DueParsingTests(TestCase):
    """Tests for /due directive parsing."""

    def test_no_due_directive(self):
        """Test parsing item without /due."""
        items = parse_list_text("- simple task")
        self.assertEqual(items[0].text, "simple task")
        self.assertEqual(items[0].text_raw, "simple task")
        self.assertIsNone(items[0].due)

    def test_due_tomorrow(self):
        """Test parsing /due tomorrow."""
        from datetime import datetime
        ref_date = datetime(2026, 2, 2, 10, 0, 0)
        items = parse_list_text("- call Alice /due tomorrow", reference_date=ref_date)

        self.assertEqual(items[0].text, "call Alice")
        self.assertEqual(items[0].text_raw, "call Alice /due tomorrow")
        self.assertIsNotNone(items[0].due)
        self.assertEqual(items[0].due.raw, "tomorrow")
        self.assertIsNotNone(items[0].due.parsed)
        self.assertEqual(items[0].due.parsed.day, 3)  # Feb 3
        self.assertFalse(items[0].due.needs_review)

    def test_due_tomorrow_with_time(self):
        """Test parsing /due tomorrow 7pm."""
        from datetime import datetime
        ref_date = datetime(2026, 2, 2, 10, 0, 0)
        items = parse_list_text("- meeting /due tomorrow 7pm", reference_date=ref_date)

        self.assertIsNotNone(items[0].due)
        self.assertIsNotNone(items[0].due.parsed)
        self.assertEqual(items[0].due.parsed.hour, 19)
        self.assertFalse(items[0].due.needs_review)

    def test_due_specific_date(self):
        """Test parsing /due 4/15."""
        from datetime import datetime
        ref_date = datetime(2026, 2, 2, 10, 0, 0)
        items = parse_list_text("- taxes /due 4/15", reference_date=ref_date)

        self.assertIsNotNone(items[0].due)
        self.assertEqual(items[0].due.raw, "4/15")
        self.assertIsNotNone(items[0].due.parsed)
        self.assertEqual(items[0].due.parsed.month, 4)
        self.assertEqual(items[0].due.parsed.day, 15)
        self.assertFalse(items[0].due.needs_review)

    def test_due_next_weekday(self):
        """Test parsing /due next Friday."""
        from datetime import datetime
        # Monday Feb 2, 2026
        ref_date = datetime(2026, 2, 2, 10, 0, 0)
        items = parse_list_text("- report /due next Friday", reference_date=ref_date)

        self.assertIsNotNone(items[0].due)
        self.assertIsNotNone(items[0].due.parsed)
        # Next Friday from Monday Feb 2 should be Feb 6
        self.assertEqual(items[0].due.parsed.weekday(), 4)  # Friday
        self.assertFalse(items[0].due.needs_review)

    def test_due_weekday_with_time(self):
        """Test parsing /due Friday 5pm."""
        from datetime import datetime
        ref_date = datetime(2026, 2, 2, 10, 0, 0)  # Monday
        items = parse_list_text("- meeting /due Friday 5pm", reference_date=ref_date)

        self.assertIsNotNone(items[0].due)
        self.assertIsNotNone(items[0].due.parsed)
        self.assertEqual(items[0].due.parsed.hour, 17)
        self.assertFalse(items[0].due.needs_review)

    def test_due_today(self):
        """Test parsing /due today."""
        from datetime import datetime
        ref_date = datetime(2026, 2, 2, 10, 0, 0)
        items = parse_list_text("- urgent /due today", reference_date=ref_date)

        self.assertIsNotNone(items[0].due)
        self.assertIsNotNone(items[0].due.parsed)
        self.assertEqual(items[0].due.parsed.day, 2)
        self.assertFalse(items[0].due.needs_review)

    def test_due_ambiguous_marks_needs_review(self):
        """Test that ambiguous dates mark needs_review."""
        items = parse_list_text("- task /due soon-ish maybe")

        self.assertIsNotNone(items[0].due)
        self.assertEqual(items[0].due.raw, "soon-ish maybe")
        self.assertIsNone(items[0].due.parsed)
        self.assertTrue(items[0].due.needs_review)

    def test_due_in_sub_item(self):
        """Test /due in a sub-item."""
        from datetime import datetime
        ref_date = datetime(2026, 2, 2, 10, 0, 0)
        items = parse_list_text("- parent\n  - child /due tomorrow", reference_date=ref_date)

        child = items[0].children[0]
        self.assertEqual(child.text, "child")
        self.assertEqual(child.text_raw, "child /due tomorrow")
        self.assertIsNotNone(child.due)
        self.assertFalse(child.due.needs_review)

    def test_serialize_preserves_due(self):
        """Test that serializing preserves /due directive."""
        text = "- task /due tomorrow"
        items = parse_list_text(text)
        result = serialize_list_items(items)
        self.assertEqual(result, text)

    def test_to_dict_includes_due(self):
        """Test that to_dict includes due info."""
        from datetime import datetime
        ref_date = datetime(2026, 2, 2, 10, 0, 0)
        items = parse_list_text("- task /due tomorrow", reference_date=ref_date)

        item_dict = items[0].to_dict()
        self.assertIn("due", item_dict)
        self.assertIsNotNone(item_dict["due"])
        self.assertEqual(item_dict["due"]["raw"], "tomorrow")
        self.assertIsNotNone(item_dict["due"]["parsed"])
        self.assertFalse(item_dict["due"]["needs_review"])

    def test_api_returns_due_info(self):
        """Test that API returns due info in items."""
        user = User.objects.create_user(
            username="duetest",
            email="due@test.com",
            password="test123",
        )
        user_ct = ContentType.objects.get_for_model(User)

        lst = List.objects.create(
            title="Due Test",
            body_text="- task /due tomorrow\n- no due",
            submitted_by=user,
            sponsor_content_type=user_ct,
            sponsor_object_id=user.id,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(f"/api/lists/{lst.id}/")

        self.assertEqual(response.status_code, 200)
        items = response.data["items"]
        self.assertEqual(len(items), 2)

        # First item has due
        self.assertIsNotNone(items[0]["due"])
        self.assertEqual(items[0]["due"]["raw"], "tomorrow")
        self.assertEqual(items[0]["text"], "task")

        # Second item has no due
        self.assertIsNone(items[1]["due"])
