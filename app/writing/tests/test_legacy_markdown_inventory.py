import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import SimpleTestCase

from writing.importers.legacy_markdown_inventory import (
    inventory_legacy_archive,
    parse_legacy_document,
)


class LegacyMarkdownInventoryTests(SimpleTestCase):
    def test_parses_legacy_metadata_separately_from_body(self):
        metadata, body, content_format, warnings = parse_legacy_document(
            "Title: Before the Aftermath\n"
            "Tags: inside-ptsd, time\n"
            "Date: 2018-06-23 16:11\n"
            "Authors: Mark Alan Lilly\n"
            "Collection: Inside PTSD\n\n"
            "The body begins here.\n"
        )

        self.assertEqual(content_format, "legacy_header")
        self.assertEqual(metadata["collection"], "Inside PTSD")
        self.assertEqual(metadata["tags"], "inside-ptsd, time")
        self.assertEqual(body, "The body begins here.\n")
        self.assertEqual(warnings, [])

    def test_inventory_preserves_collection_and_flags_drafts_and_duplicates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            body = (
                "Title: Before the Aftermath\n"
                "Tags: inside-ptsd, time\n"
                "Date: 2018-06-23\n"
                "Authors: Mark Alan Lilly\n"
                "Collection: Inside PTSD\n\n"
                "The body begins here.\n"
            )
            (root / "Daily").mkdir()
            (root / "Daily" / "one.md").write_text(body, encoding="utf-8")
            (root / "Daily" / "one-copy.md.draft").write_text(body, encoding="utf-8")

            manifest = inventory_legacy_archive(root)

        self.assertEqual(manifest["summary"]["file_count"], 2)
        self.assertEqual(manifest["summary"]["exact_duplicate_group_count"], 1)
        self.assertEqual(manifest["summary"]["collections"], {"Inside PTSD": 2})
        first = manifest["items"][0]
        draft = next(item for item in manifest["items"] if item["source_status_hint"] == "draft")
        self.assertEqual(first["proposed"]["collection"], "Inside PTSD")
        self.assertEqual(first["proposed"]["tags"], ["inside-ptsd", "time"])
        self.assertEqual(draft["publication_decision"], "review_required")
        self.assertTrue(first["exact_duplicate_paths"])

    def test_management_command_writes_json_without_database_access(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "note.md").write_text("Title: Note\n\nBody.\n", encoding="utf-8")
            output = root / "manifest.json"

            call_command("preview_legacy_markdown", str(source), output=str(output))
            manifest = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(manifest["summary"]["file_count"], 1)
        self.assertEqual(manifest["items"][0]["proposed"]["title"], "Note")
