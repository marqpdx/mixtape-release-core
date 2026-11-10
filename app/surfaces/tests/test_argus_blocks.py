import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from surfaces.services.argus_blocks import read_audit_block, read_audit_blocks

BLOCK_MD = """---
title: 'Audit Block: help-fidelity-01'
status: canon
class: spec
block_state: ready
block: help-fidelity-01
domain: help
finding_types:
- references-hidden
- outdated-description
---

# Audit Block: help-fidelity-01
"""


class ArgusBlocksTests(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        (self.root / "decisions" / "argus" / "audit-blocks").mkdir(parents=True)
        (self.root / "decisions" / "argus" / "audit-runs").mkdir(parents=True)
        (self.root / "decisions" / "argus" / "audit-blocks" / "help-fidelity-01.md").write_text(BLOCK_MD)
        (self.root / "decisions" / "argus" / "audit-runs" / "help-fidelity-01-2026-07-01.md").write_text("old run")
        (self.root / "decisions" / "argus" / "audit-runs" / "help-fidelity-01-2026-10-08.md").write_text("new run")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_unavailable_when_puddlejump_path_unset(self):
        with override_settings(PUDDLEJUMP_PATH=None):
            blocks, reason = read_audit_blocks()
        self.assertEqual(blocks, [])
        self.assertTrue(reason)

    def test_reads_block_with_finding_types_and_latest_run_date(self):
        with override_settings(PUDDLEJUMP_PATH=str(self.root)):
            blocks, reason = read_audit_blocks()
        self.assertEqual(reason, "")
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertEqual(block.slug, "help-fidelity-01")
        self.assertEqual(block.domain, "help")
        self.assertEqual(block.block_state, "ready")
        self.assertEqual(set(block.finding_types), {"references-hidden", "outdated-description"})
        self.assertEqual(block.last_run_at, "2026-10-08")

    def test_read_single_block_by_slug(self):
        with override_settings(PUDDLEJUMP_PATH=str(self.root)):
            block, reason = read_audit_block("help-fidelity-01")
            self.assertEqual(reason, "")
            self.assertIsNotNone(block)

            missing, missing_reason = read_audit_block("no-such-block")
            self.assertIsNone(missing)
            self.assertTrue(missing_reason)
