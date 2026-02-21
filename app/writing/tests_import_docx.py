# writing/tests_import_docx.py
"""
Tests for the DOCX import system:
- docx_to_tiptap parser
- outline generation
- comment extraction
- ImportReceipt idempotency
- management command
"""

import hashlib
import io
import os
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from docx import Document
from docx.shared import Pt

from writing.importers.docx_to_tiptap import (
    docx_to_tiptap,
    generate_outline_from_headings,
    extract_title,
    count_nodes_by_type,
)
from writing.importers.docx_comments import extract_docx_comments
from writing.models import ImportReceipt, WritingPiece
from groups.models import Group

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers — programmatic .docx fixture creation
# ---------------------------------------------------------------------------

def _make_simple_docx(tmp_dir: str, filename: str = "test.docx") -> str:
    """Create a minimal docx with a heading and paragraph."""
    doc = Document()
    doc.add_heading("Test Title", level=1)
    doc.add_paragraph("Hello world, this is a test paragraph.")
    path = os.path.join(tmp_dir, filename)
    doc.save(path)
    return path


def _make_rich_docx(tmp_dir: str, filename: str = "rich.docx") -> str:
    """Create a docx with headings, lists, bold/italic, links."""
    doc = Document()
    doc.add_heading("Document Title", level=1)
    doc.add_paragraph("Introduction paragraph with plain text.")

    doc.add_heading("Chapter One", level=2)
    p = doc.add_paragraph()
    run_bold = p.add_run("Bold text ")
    run_bold.bold = True
    run_italic = p.add_run("and italic text ")
    run_italic.italic = True
    p.add_run("and normal text.")

    doc.add_heading("Chapter Two", level=2)
    doc.add_paragraph("Another paragraph here.")

    doc.add_heading("Subsection", level=3)
    doc.add_paragraph("Subsection content.")

    # Add a bulleted list
    doc.add_paragraph("First bullet", style="List Bullet")
    doc.add_paragraph("Second bullet", style="List Bullet")

    # Add a numbered list
    doc.add_paragraph("Step one", style="List Number")
    doc.add_paragraph("Step two", style="List Number")

    path = os.path.join(tmp_dir, filename)
    doc.save(path)
    return path


def _make_empty_docx(tmp_dir: str, filename: str = "empty.docx") -> str:
    """Create a docx with no content."""
    doc = Document()
    path = os.path.join(tmp_dir, filename)
    doc.save(path)
    return path


def _make_docx_with_comments(tmp_dir: str, filename: str = "commented.docx") -> str:
    """Create a docx and manually inject comments into its XML."""
    # First create a basic doc
    doc = Document()
    doc.add_heading("Review Document", level=1)
    doc.add_paragraph("This paragraph has a comment.")
    path = os.path.join(tmp_dir, filename)
    doc.save(path)

    # Now inject comments.xml into the zip
    comments_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:comment w:id="1" w:author="Alice" w:date="2026-01-15T10:30:00Z">
    <w:p><w:r><w:t>Great point here!</w:t></w:r></w:p>
  </w:comment>
  <w:comment w:id="2" w:author="Bob" w:date="2026-01-15T11:00:00Z">
    <w:p><w:r><w:t>Need to revise this section.</w:t></w:r></w:p>
  </w:comment>
</w:comments>"""

    # Read existing zip, add comments.xml, write back
    with zipfile.ZipFile(path, "r") as zin:
        contents = {}
        for name in zin.namelist():
            contents[name] = zin.read(name)

    contents["word/comments.xml"] = comments_xml.encode("utf-8")

    with zipfile.ZipFile(path, "w") as zout:
        for name, data in contents.items():
            zout.writestr(name, data)

    return path


def _create_test_user() -> User:
    return User.objects.create_user(
        username="import_tester",
        email="importer@example.com",
        password="testpass123",
    )


def _create_test_group(user: User) -> Group:
    group = Group(
        title="Import Group",
        slug="import-group",
        description="Test group for imports",
        group_type="community",
        decorators=[],
        additional_permissions=[],
    )
    group.set_sponsor(user)
    group.set_submitted_by(user)
    group.author = user
    group.author_name = user.get_full_name() or user.username
    group.save()
    return group


# ---------------------------------------------------------------------------
# Parser Tests (no Django needed for these, but TestCase is fine)
# ---------------------------------------------------------------------------

class DocxToTiptapParserTests(TestCase):

    def test_simple_doc_produces_valid_tiptap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)
            result = docx_to_tiptap(path)

        self.assertEqual(result["type"], "doc")
        self.assertIsInstance(result["content"], list)
        self.assertGreater(len(result["content"]), 0)

    def test_heading_has_correct_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)
            result = docx_to_tiptap(path)

        headings = [n for n in result["content"] if n["type"] == "heading"]
        self.assertEqual(len(headings), 1)
        self.assertEqual(headings[0]["attrs"]["level"], 1)

    def test_heading_has_text_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)
            result = docx_to_tiptap(path)

        headings = [n for n in result["content"] if n["type"] == "heading"]
        text_nodes = headings[0].get("content", [])
        self.assertTrue(any(t.get("text") == "Test Title" for t in text_nodes))

    def test_paragraph_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)
            result = docx_to_tiptap(path)

        paragraphs = [n for n in result["content"] if n["type"] == "paragraph"]
        self.assertGreaterEqual(len(paragraphs), 1)

    def test_block_ids_on_all_block_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            result = docx_to_tiptap(path)

        for node in result["content"]:
            if node["type"] in ("heading", "paragraph", "blockquote"):
                self.assertIn("data-block-id", node.get("attrs", {}),
                              f"Missing data-block-id on {node['type']}")

    def test_bold_italic_marks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            result = docx_to_tiptap(path)

        # Find text nodes with bold mark
        bold_found = False
        italic_found = False

        def walk(node):
            nonlocal bold_found, italic_found
            if node.get("type") == "text":
                marks = node.get("marks", [])
                mark_types = [m["type"] for m in marks]
                if "bold" in mark_types:
                    bold_found = True
                if "italic" in mark_types:
                    italic_found = True
            for child in node.get("content", []):
                walk(child)

        walk(result)
        self.assertTrue(bold_found, "Expected at least one bold text node")
        self.assertTrue(italic_found, "Expected at least one italic text node")

    def test_multiple_heading_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            result = docx_to_tiptap(path)

        headings = [n for n in result["content"] if n["type"] == "heading"]
        levels = {h["attrs"]["level"] for h in headings}
        self.assertIn(1, levels)
        self.assertIn(2, levels)
        self.assertIn(3, levels)

    def test_bullet_list_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            result = docx_to_tiptap(path)

        list_nodes = [n for n in result["content"] if n["type"] == "bulletList"]
        self.assertGreaterEqual(len(list_nodes), 1)

    def test_ordered_list_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            result = docx_to_tiptap(path)

        list_nodes = [n for n in result["content"] if n["type"] == "orderedList"]
        self.assertGreaterEqual(len(list_nodes), 1)

    def test_empty_doc_returns_single_paragraph(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_empty_docx(tmp)
            result = docx_to_tiptap(path)

        self.assertEqual(result["type"], "doc")
        self.assertEqual(len(result["content"]), 1)
        self.assertEqual(result["content"][0]["type"], "paragraph")

    def test_bytes_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)
            file_bytes = Path(path).read_bytes()

        result = docx_to_tiptap(file_bytes)
        self.assertEqual(result["type"], "doc")
        self.assertGreater(len(result["content"]), 0)


# ---------------------------------------------------------------------------
# Outline Generation Tests
# ---------------------------------------------------------------------------

class OutlineGenerationTests(TestCase):

    def test_outline_from_headings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            tiptap = docx_to_tiptap(path)

        specs = generate_outline_from_headings(tiptap)
        self.assertGreater(len(specs), 0)

        # Each spec should have required keys
        for spec in specs:
            self.assertIn("title", spec)
            self.assertIn("order_index", spec)
            self.assertIn("anchor_target", spec)
            self.assertIn("level", spec)

    def test_markers_inserted_in_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            tiptap = docx_to_tiptap(path)

        specs = generate_outline_from_headings(tiptap)

        # Find outlineMarker nodes in the content
        marker_ids = set()
        for node in tiptap["content"]:
            if node.get("type") == "outlineMarker":
                marker_ids.add(node["attrs"]["nodeId"])

        spec_ids = {s["anchor_target"] for s in specs}
        self.assertEqual(marker_ids, spec_ids)

    def test_order_index_sequential(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            tiptap = docx_to_tiptap(path)

        specs = generate_outline_from_headings(tiptap)
        indices = [s["order_index"] for s in specs]
        self.assertEqual(indices, list(range(len(specs))))

    def test_empty_doc_no_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_empty_docx(tmp)
            tiptap = docx_to_tiptap(path)

        specs = generate_outline_from_headings(tiptap)
        self.assertEqual(len(specs), 0)


# ---------------------------------------------------------------------------
# Title Extraction Tests
# ---------------------------------------------------------------------------

class TitleExtractionTests(TestCase):

    def test_extract_title_from_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)
            tiptap = docx_to_tiptap(path)

        title = extract_title(tiptap)
        self.assertEqual(title, "Test Title")

    def test_extract_title_none_for_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_empty_docx(tmp)
            tiptap = docx_to_tiptap(path)

        title = extract_title(tiptap)
        self.assertIsNone(title)


# ---------------------------------------------------------------------------
# Node Count Tests
# ---------------------------------------------------------------------------

class NodeCountTests(TestCase):

    def test_count_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            tiptap = docx_to_tiptap(path)

        counts = count_nodes_by_type(tiptap)
        self.assertIn("doc", counts)
        self.assertIn("heading", counts)
        self.assertIn("paragraph", counts)
        self.assertGreater(counts["heading"], 0)


# ---------------------------------------------------------------------------
# Comment Extraction Tests
# ---------------------------------------------------------------------------

class CommentExtractionTests(TestCase):

    def test_extract_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_docx_with_comments(tmp)
            comments = extract_docx_comments(path)

        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0]["author"], "Alice")
        self.assertEqual(comments[0]["text"], "Great point here!")
        self.assertEqual(comments[1]["author"], "Bob")

    def test_no_comments_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)
            comments = extract_docx_comments(path)

        self.assertEqual(len(comments), 0)


# ---------------------------------------------------------------------------
# ImportReceipt / Management Command Tests
# ---------------------------------------------------------------------------

class ImportReceiptTests(TestCase):

    def setUp(self):
        self.user = _create_test_user()
        self.group = _create_test_group(self.user)

    def test_dry_run_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)
            out = io.StringIO()
            call_command(
                "writing_import_docx",
                f"--path={path}",
                f"--author={self.user.email}",
                f"--sponsor=groups.group:{self.group.id}",
                "--dry-run",
                stdout=out,
            )

        self.assertEqual(WritingPiece.objects.filter(author=self.user, writing_kind="dispatch").count(), 0)
        self.assertEqual(ImportReceipt.objects.count(), 0)
        self.assertIn("DRY RUN", out.getvalue())

    def test_import_creates_piece_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)
            out = io.StringIO()
            call_command(
                "writing_import_docx",
                f"--path={path}",
                f"--author={self.user.email}",
                f"--sponsor=groups.group:{self.group.id}",
                stdout=out,
            )

        piece = WritingPiece.objects.filter(author=self.user, writing_kind="dispatch").first()
        self.assertIsNotNone(piece)
        self.assertEqual(piece.title, "Test Title")
        self.assertEqual(piece.status, "draft")
        self.assertEqual(piece.body_json["type"], "doc")

        receipt = ImportReceipt.objects.filter(created_writing_piece=piece).first()
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.source_type, "docx")
        self.assertEqual(receipt.original_filename, "test.docx")
        self.assertEqual(receipt.imported_by, self.user)

    def test_idempotency_skips_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)

            # First import
            call_command(
                "writing_import_docx",
                f"--path={path}",
                f"--author={self.user.email}",
                f"--sponsor=groups.group:{self.group.id}",
                stdout=io.StringIO(),
            )

            # Second import — should be skipped
            out = io.StringIO()
            call_command(
                "writing_import_docx",
                f"--path={path}",
                f"--author={self.user.email}",
                f"--sponsor=groups.group:{self.group.id}",
                stdout=out,
            )

        self.assertIn("Already imported", out.getvalue())
        self.assertEqual(WritingPiece.objects.filter(author=self.user, writing_kind="dispatch").count(), 1)

    def test_force_bypasses_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)

            # First import
            call_command(
                "writing_import_docx",
                f"--path={path}",
                f"--author={self.user.email}",
                f"--sponsor=groups.group:{self.group.id}",
                stdout=io.StringIO(),
            )

            # Second import with --force
            call_command(
                "writing_import_docx",
                f"--path={path}",
                f"--author={self.user.email}",
                f"--sponsor=groups.group:{self.group.id}",
                "--force",
                stdout=io.StringIO(),
            )

        self.assertEqual(WritingPiece.objects.filter(author=self.user, writing_kind="dispatch").count(), 2)

    def test_enable_outline_creates_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            call_command(
                "writing_import_docx",
                f"--path={path}",
                f"--author={self.user.email}",
                f"--sponsor=groups.group:{self.group.id}",
                "--enable-outline",
                stdout=io.StringIO(),
            )

        from dispatch.models import DispatchOutlineNode

        piece = WritingPiece.objects.filter(author=self.user, writing_kind="dispatch").first()
        self.assertIsNotNone(piece)
        self.assertTrue(piece.enable_outline)

        nodes = DispatchOutlineNode.objects.filter(writing_piece=piece)
        self.assertGreater(nodes.count(), 0)

        # Each node should have an anchor_target
        for node in nodes:
            self.assertIsNotNone(node.anchor_target)

    def test_title_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_simple_docx(tmp)
            call_command(
                "writing_import_docx",
                f"--path={path}",
                f"--author={self.user.email}",
                f"--sponsor=groups.group:{self.group.id}",
                "--title=Custom Title",
                stdout=io.StringIO(),
            )

        piece = WritingPiece.objects.filter(author=self.user, writing_kind="dispatch").first()
        self.assertEqual(piece.title, "Custom Title")

    def test_reading_time_calculated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_rich_docx(tmp)
            call_command(
                "writing_import_docx",
                f"--path={path}",
                f"--author={self.user.email}",
                f"--sponsor=groups.group:{self.group.id}",
                stdout=io.StringIO(),
            )

        piece = WritingPiece.objects.filter(author=self.user, writing_kind="dispatch").first()
        self.assertIsNotNone(piece.reading_time)

    def test_comments_stored_in_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_docx_with_comments(tmp)
            call_command(
                "writing_import_docx",
                f"--path={path}",
                f"--author={self.user.email}",
                f"--sponsor=groups.group:{self.group.id}",
                stdout=io.StringIO(),
            )

        receipt = ImportReceipt.objects.first()
        self.assertIsNotNone(receipt)
        comments = receipt.import_notes.get("comments", [])
        self.assertEqual(len(comments), 2)
