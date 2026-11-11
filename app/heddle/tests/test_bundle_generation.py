import json
import tempfile
from pathlib import Path
from unittest import TestCase

import yaml

from heddle.bundle import BUNDLE_PATH, digest
from heddle.generate_bundle import generate


class BundleGenerationTests(TestCase):
    def checkout(self, directory):
        bundle = json.loads(BUNDLE_PATH.read_text())
        root = Path(directory)
        for relative, entry in bundle["files"].items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(entry["text"])
        manifest = {"library_version": bundle["library_version"],
                    "verticals": bundle["selection"]["verticals"],
                    "strategies": [{"entries": bundle["selection"]["strategies"]}]}
        if "schema_definitions" in bundle["selection"]:
            manifest["schema_definitions"] = bundle["selection"]["schema_definitions"]
        (root / "manifest.yaml").write_text(yaml.safe_dump(manifest))
        return bundle

    def test_rebuild_is_exact_and_changed_dependency_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            original = self.checkout(directory)
            rebuilt = generate(directory, original["source_commit"])
            rebuilt["digest"] = digest(rebuilt)
            self.assertEqual(original, rebuilt)
            path = Path(directory) / "writing/character.extraction.md"
            path.write_text(path.read_text() + "\nChanged canonical guidance.\n")
            changed = generate(directory, original["source_commit"])
            self.assertNotEqual(digest(changed), original["digest"])

    def test_retained_old_version_is_bundled_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            original = self.checkout(directory)
            root = Path(directory)
            schema = json.loads((root / "writing/character.schema.json").read_text())
            schema["properties"]["shape_version"]["const"] = "0.0.9"
            schema["$id"] = "urn:contour:writing.character:0.0.9"
            old = root / "writing/versions/character.0.0.9.schema.json"
            old.parent.mkdir(exist_ok=True)
            old.write_text(json.dumps(schema))
            rebuilt = generate(root, original["source_commit"])
            self.assertIn("writing.character@0.0.9", rebuilt["schemas"])
            self.assertIn("writing.character@0.1.0", rebuilt["schemas"])

    def test_conflicting_retained_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original = self.checkout(directory)
            root = Path(directory)
            schema = json.loads((root / "writing/character.schema.json").read_text())
            schema["required"].append("invented")
            version = schema["properties"]["shape_version"]["const"]
            old = root / f"writing/versions/character.{version}.schema.json"
            old.parent.mkdir(exist_ok=True)
            old.write_text(json.dumps(schema))
            with self.assertRaisesRegex(ValueError, "Conflicting retained schema"):
                generate(root, original["source_commit"])
