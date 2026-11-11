"""Offline resolver prerequisite; synthetic schemas, never canonical activation."""
from copy import deepcopy
import json
import socket
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import yaml
from jsonschema import ValidationError
from referencing.exceptions import Unresolvable

from heddle.bundle import (BUNDLE_PATH, check_schema_references, digest,
    schema_registry, schema_validator, validate_shaped_payload, validate_sighting)
from heddle.generate_bundle import generate
from heddle.tests import test_bundle_generation as generation_fixtures

PROVENANCE_ID = "urn:contour:shared.test_provenance:0.1.0"
SHAPE_ID = "urn:contour:writing.test:0.2.0"
PROVENANCE = {"$schema": "http://json-schema.org/draft-07/schema#", "$id": PROVENANCE_ID,
    "type": "object", "required": ["actor_id", "recorded_at"], "additionalProperties": False,
    "properties": {"actor_id": {"type": "string", "format": "uuid"},
                   "recorded_at": {"type": "string", "format": "date-time"}}}
SHAPE = {"$schema": "http://json-schema.org/draft-07/schema#", "$id": SHAPE_ID,
    "type": "object", "required": ["shape_id", "shape_version", "provenance"],
    "properties": {"shape_id": {"const": "writing.test"}, "shape_version": {"const": "0.2.0"},
                   "provenance": {"$ref": PROVENANCE_ID}}, "additionalProperties": False}
VALUE = {"shape_id": "writing.test", "shape_version": "0.2.0", "provenance": {
    "actor_id": "00000000-0000-0000-0000-000000000001", "recorded_at": "2026-11-10T01:02:03Z"}}


def fixture_bundle():
    files = {}
    for path, schema in (("shared/test.schema.json", PROVENANCE), ("writing/test.schema.json", SHAPE)):
        text = json.dumps(schema)
        import hashlib
        files[path] = {"text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
    return {"files": files, "schemas": {"writing.test@0.2.0": "writing/test.schema.json"}}


class SchemaRegistryTests(TestCase):
    def setUp(self):
        self.guard = patch.object(socket, "getaddrinfo", side_effect=AssertionError("No schema network"))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.connect = patch.object(socket.socket, "connect", side_effect=AssertionError("No schema network"))
        self.connect.start()
        self.addCleanup(self.connect.stop)

    def test_shared_urn_resolves_only_from_bundle(self):
        bundle = fixture_bundle()
        check_schema_references(bundle)
        schema_validator(SHAPE, bundle=bundle).validate(VALUE)
        with patch("heddle.bundle._load", return_value=bundle):
            self.assertEqual(validate_sighting(VALUE), VALUE)
            self.assertEqual(validate_shaped_payload(VALUE), VALUE)

    def test_missing_remote_file_and_urn_refs_never_retrieve(self):
        for ref in ("https://example.invalid/private.schema.json", "file:///not-permitted/schema.json",
                    "urn:contour:shared.missing:0.1.0"):
            with self.subTest(ref=ref):
                bundle = fixture_bundle()
                schema = deepcopy(SHAPE)
                schema["properties"]["provenance"]["$ref"] = ref
                bundle["files"]["writing/test.schema.json"]["text"] = json.dumps(schema)
                with self.assertRaisesRegex(ValueError, "absent from the pinned bundle"):
                    check_schema_references(bundle)
                with self.assertRaises(Unresolvable):
                    schema_validator(schema, bundle=bundle).validate(VALUE)

    def test_unused_branch_ref_is_preflighted(self):
        bundle = fixture_bundle()
        schema = deepcopy(SHAPE)
        schema["properties"]["unused"] = {"$ref": "https://example.invalid/unused"}
        bundle["files"]["writing/test.schema.json"]["text"] = json.dumps(schema)
        with self.assertRaisesRegex(ValueError, "absent from the pinned bundle"):
            check_schema_references(bundle)

    def test_uuid_and_date_time_formats_are_enforced(self):
        for field, values in {
            "actor_id": ["not-uuid", "00000000000000000000000000000001"],
            "recorded_at": ["yesterday", "2026-02-30T01:02:03Z", "2026-11-10", "2026-11-10T01:02:03", "2026-11-10T25:00:00Z"],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    data = deepcopy(VALUE)
                    data["provenance"][field] = value
                    with self.assertRaises(ValidationError):
                        schema_validator(SHAPE, bundle=fixture_bundle()).validate(data)
        for time in ("2026-11-10T01:02:03.123456Z", "2026-11-10t01:02:03z", "2026-11-10T01:02:03+00:00"):
            data = deepcopy(VALUE)
            data["provenance"]["recorded_at"] = time
            schema_validator(SHAPE, bundle=fixture_bundle()).validate(data)

    def test_conflicting_resource_id_is_refused(self):
        bundle = fixture_bundle()
        entry = deepcopy(bundle["files"]["shared/test.schema.json"])
        schema = deepcopy(PROVENANCE)
        schema["required"].append("unknown")
        entry["text"] = json.dumps(schema)
        bundle["files"]["shared/other.schema.json"] = entry
        with self.assertRaisesRegex(ValueError, "Conflicting bundled schema identifier"):
            schema_registry(bundle)

    def test_local_fragment_and_relative_path_refs(self):
        schema = {"$id": "writing/wrapper.schema.json", "definitions": {"local": {"type": "string"}},
            "properties": {"local": {"$ref": "#/definitions/local"},
                           "shared": {"$ref": "../shared/test.schema.json"}}}
        bundle = fixture_bundle()
        bundle["files"]["writing/wrapper.schema.json"] = {"text": json.dumps(schema)}
        check_schema_references(bundle)
        schema_validator(schema, bundle=bundle).validate({"local": "ok", "shared": VALUE["provenance"]})
        with self.assertRaises(ValidationError):
            schema_validator(schema, bundle=bundle).validate({"local": 12})

    def test_digest_check_still_rejects_tampered_files(self):
        from heddle import bundle as module
        bundle = fixture_bundle()
        bundle["digest"] = digest(bundle)
        bundle["files"]["shared/test.schema.json"]["text"] += " "
        bundle["digest"] = digest({k: v for k, v in bundle.items() if k != "digest"})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"bundle.json"
            target.write_text(json.dumps(bundle))
            module._load.cache_clear()
            try:
                with patch.object(module, "BUNDLE_PATH", target):
                    with self.assertRaisesRegex(ValueError, "file digest mismatch"):
                        module._load()
            finally:
                module._load.cache_clear()


class DefinitionGenerationTests(TestCase):
    def checkout(self, directory):
        return generation_fixtures.BundleGenerationTests().checkout(directory)

    def add_definition(self, directory):
        root=Path(directory)
        original=self.checkout(root)
        manifest=yaml.safe_load((root/"manifest.yaml").read_text())
        manifest.setdefault("schema_definitions", []).append({"id": "shared.test_provenance", "version": "0.1.0",
            "schema_file": "shared/test.schema.json"})
        path=root/"shared/test.schema.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(PROVENANCE))
        (root/"manifest.yaml").write_text(yaml.safe_dump(manifest))
        return original,manifest

    def test_current_bundle_remains_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            original=self.checkout(directory)
            result=generate(directory,original["source_commit"])
            result["digest"]=digest(result)
            self.assertEqual(original,result)

    def test_only_explicitly_selected_shared_definitions_are_included(self):
        with tempfile.TemporaryDirectory() as directory:
            original,_=self.add_definition(directory)
            (Path(directory)/"shared/unselected.schema.json").write_text('{"type":"string"}')
            result=generate(directory,original["source_commit"])
            expected = dict(original.get("definitions", {}))
            expected["shared.test_provenance@0.1.0"] = "shared/test.schema.json"
            self.assertEqual(result["definitions"], expected)
            self.assertNotIn("shared/unselected.schema.json",result["files"])

    def test_definition_id_mismatch_and_duplicate_are_rejected(self):
        for failure in ("identity", "duplicate", "path"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                original,manifest=self.add_definition(directory)
                if failure=="identity":
                    manifest["schema_definitions"][-1]["version"]="0.9.0"
                elif failure=="duplicate":
                    manifest["schema_definitions"].append(manifest["schema_definitions"][-1])
                else:
                    manifest["schema_definitions"][-1]["schema_file"]="../outside.schema.json"
                (Path(directory)/"manifest.yaml").write_text(yaml.safe_dump(manifest))
                with self.assertRaises(ValueError):
                    generate(directory,original["source_commit"])

    def test_recognition_strategy_must_be_explicit_and_active(self):
        with tempfile.TemporaryDirectory() as directory:
            original=self.checkout(directory)
            root=Path(directory)
            manifest=yaml.safe_load((root/"manifest.yaml").read_text())
            entry={"id":"writing.fiction_note_recognition","version":"0.1.0",
                "contract_file":"puddlejump/reference/contour/writing/strategies/fiction-note-recognition.strategy.yaml",
                "prose_file":"puddlejump/reference/contour/writing/strategies/fiction-note-recognition.md"}
            manifest["strategies"][0]["entries"] = [
                item for item in manifest["strategies"][0]["entries"]
                if item["id"] != "writing.fiction_note_recognition"
            ]
            (root/"manifest.yaml").write_text(yaml.safe_dump(manifest))
            for name in ("fiction-note-recognition.strategy.yaml","fiction-note-recognition.md"):
                (root/"writing/strategies"/name).write_text("test only")
            result=generate(root,original["source_commit"])
            self.assertEqual(len(result["selection"]["strategies"]),1)
            manifest["strategies"][0]["entries"].append(entry)
            (root/"manifest.yaml").write_text(yaml.safe_dump(manifest))
            result=generate(root,original["source_commit"])
            self.assertEqual(len(result["selection"]["strategies"]),2)
            entry["contract_file"]="puddlejump/reference/contour/_proposed/not-active.yaml"
            (root/"manifest.yaml").write_text(yaml.safe_dump(manifest))
            with self.assertRaisesRegex(ValueError,"active canonical shelf"):
                generate(root,original["source_commit"])


class RetainedDescriptorTests(TestCase):
    def test_existing_strategy_keeps_original_cues_after_shelf_version_bump(self):
        from folio.interpretation import strategy
        bundle=json.loads(BUNDLE_PATH.read_text())
        for name in ("character","setting"):
            current=f"writing/{name}.shape.yaml"
            bundle["files"].setdefault(f"writing/versions/{name}.0.1.0.shape.yaml", deepcopy(bundle["files"][current]))
            document=yaml.safe_load(bundle["files"][current]["text"])
            document["version"]="0.2.0"
            document["synonyms"]=["not-an-old-cue"]
            bundle["files"][current]["text"]=yaml.safe_dump(document)
        with patch.object(strategy,"_load",return_value=bundle):
            cues=strategy.dependencies()["cues"]
            self.assertIn(("writing.character","character"),cues)
            self.assertNotIn(("writing.character","not-an-old-cue"),cues)
        bundle["files"].pop("writing/versions/character.0.1.0.shape.yaml")
        with patch.object(strategy,"_load",return_value=bundle):
            with self.assertRaisesRegex(ValidationError,"descriptor unavailable"):
                strategy.dependencies()

    def test_retained_descriptor_is_carried_by_generator(self):
        with tempfile.TemporaryDirectory() as directory:
            original=generation_fixtures.BundleGenerationTests().checkout(directory)
            root=Path(directory)
            retained=root/"writing/versions/character.0.1.0.shape.yaml"
            retained.parent.mkdir(exist_ok=True)
            if not retained.exists():
                retained.write_text((root/"writing/character.shape.yaml").read_text())
            result=generate(root,original["source_commit"])
            self.assertIn("writing/versions/character.0.1.0.shape.yaml",result["files"])


class OrderedValidationTests(TestCase):
    def test_worker_output_uses_pinned_registry_and_formats(self):
        from types import SimpleNamespace
        from heddle.ordered import validate_model_output
        step=SimpleNamespace(id="recognition",response_schema=SHAPE,validate=None)
        reading=SimpleNamespace(steps=(step,))
        child=SimpleNamespace(request_payload={"capability_payload":{"step_id":"recognition"}})
        with patch("heddle.bundle._load",return_value=fixture_bundle()):
            validate_model_output(reading,child,VALUE)
            invalid=deepcopy(VALUE)
            invalid["provenance"]["recorded_at"]="not-a-date"
            with self.assertRaises(ValidationError):
                validate_model_output(reading,child,invalid)


class ExistingPayloadFormatTests(TestCase):
    def test_argus_payload_keeps_valid_dates_and_rejects_malformed_dates(self):
        from initiatives.tests.test_findings import _payload
        validate_shaped_payload(_payload())
        with self.assertRaises(ValidationError):
            validate_shaped_payload(_payload(started_at="not-a-date"))
