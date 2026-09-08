from django.test import SimpleTestCase

from sourcework.models import NameConfidence, NameSource, NameStatus
from sourcework.services import resolve_sender_name


class ResolveSenderNameTests(SimpleTestCase):
    def test_prefers_confident_header_name(self):
        result = resolve_sender_name({
            "from_header": "Vaughn Smith <vaughn@example.com>",
            "body": "Best regards,\nSomeone Else",
        })

        self.assertEqual(result.preferred_name, "Vaughn Smith")
        self.assertEqual(result.email, "vaughn@example.com")
        self.assertEqual(result.source, NameSource.HEADER)
        self.assertEqual(result.confidence, NameConfidence.HIGH)
        self.assertEqual(result.status, NameStatus.READY)
        self.assertEqual(result.evidence_excerpt, "")

    def test_uses_signature_when_header_name_is_missing(self):
        result = resolve_sender_name({
            "from_header": "talent@example.net",
            "body": "Hello,\n\nKind regards,\nAmara Lee\nTalent Partner",
        })

        self.assertEqual(result.preferred_name, "Amara Lee")
        self.assertEqual(result.email, "talent@example.net")
        self.assertEqual(result.source, NameSource.SIGNATURE)
        self.assertEqual(result.confidence, NameConfidence.HIGH)
        self.assertEqual(result.status, NameStatus.READY)
        self.assertIn("Kind regards", result.evidence_excerpt)
        self.assertIn("Amara Lee", result.evidence_excerpt)

    def test_marks_unclear_name_for_review(self):
        result = resolve_sender_name({
            "from_header": "recruiting@example.org",
            "body": "Hello,\n\nThis role may interest you.",
        })

        self.assertEqual(result.preferred_name, "")
        self.assertEqual(result.email, "recruiting@example.org")
        self.assertEqual(result.source, NameSource.UNKNOWN)
        self.assertEqual(result.confidence, NameConfidence.LOW)
        self.assertEqual(result.status, NameStatus.NEEDS_REVIEW)
