from pathlib import Path

from django.test import TestCase

from catalyst.services.shape_library import ShapeLibrary


class ShapeLibraryContourNotLoadedTests(TestCase):
    """HD-6 (CTO, 2026-10-23): a missing Contour manifest must be loud and
    visible on every strategy lookup, not silently fall back to defaults
    with no signal for anything other than food_service.* strategies."""

    def test_missing_manifest_logs_error_and_reports_a_gap_on_any_strategy(self):
        library = ShapeLibrary(manifest_path=Path("/nonexistent/contour/manifest.yaml"))
        self.assertIsNotNone(library.load_error)

        strategy = library.get_strategy("generic.meeting_notes_to_findings")
        self.assertIsNotNone(strategy)
        self.assertEqual(
            strategy.contract_gaps,
            [{"contract_gap": "contour_not_loaded", "detail": library.load_error}],
        )

    def test_loaded_manifest_has_no_load_error(self):
        # The real Contour manifest, when present (dev/CI checkout), loads cleanly.
        library = ShapeLibrary()
        if library.load_error:
            self.skipTest("No Puddlejump/Contour checkout available in this environment.")
        self.assertIsNone(library.load_error)
