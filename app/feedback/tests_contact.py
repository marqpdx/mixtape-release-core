from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@override_settings(CACHES=LOCMEM)
class SiteContactTests(SimpleTestCase):
    url = "/api/contact"

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_sends_email_with_reply_to(self):
        response = self.client.post(self.url, {
            "name": "Ada", "email": "ada@example.com", "subject": "Hello", "message": "A question.",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.subject, "Crossroads contact: Hello")
        self.assertEqual(sent.to, ["connect@crossroads.place"])
        self.assertEqual(sent.reply_to, ["ada@example.com"])
        self.assertIn("A question.", sent.body)

    def test_subject_falls_back_to_name_and_drops_line_breaks(self):
        self.client.post(self.url, {
            "name": "Ada\nBcc: x@example.com", "email": "ada@example.com", "message": "Hi",
        }, format="json")
        self.assertEqual(mail.outbox[0].subject, "Crossroads contact: Ada Bcc: x@example.com")

    def test_missing_fields_are_refused_with_detail(self):
        response = self.client.post(self.url, {"name": "Ada", "email": "not-an-email", "message": "Hi"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Invalid email address.")
        self.assertEqual(len(mail.outbox), 0)

    def test_honeypot_is_accepted_quietly_and_not_sent(self):
        response = self.client.post(self.url, {
            "name": "Bot", "email": "bot@example.com", "message": "Spam", "website": "http://spam.example",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_send_failure_returns_500(self):
        with mock.patch("utils.email.send_transactional_email.send_transactional_email", side_effect=OSError("smtp down")):
            response = self.client.post(self.url, {"name": "Ada", "email": "ada@example.com", "message": "Hi"}, format="json")
        self.assertEqual(response.status_code, 500)
        self.assertIn("detail", response.data)


@override_settings(CACHES=LOCMEM)
class WorkingPaperResponseTests(SimpleTestCase):
    url = "/api/feedback/working-papers/respond"

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.payload = {
            "name": "Ada", "email": "ada@example.com", "organization": "Example Co",
            "response_type": "correction", "message": "Section 2 has a gap.", "may_credit": True,
            "paper_title": "Decompose Now, Localize Later", "paper_version": "0.9",
            "packet": "2026-11-08", "page_url": "https://crossroads.place/working-papers/2026-11-08/decompose",
        }

    def test_sends_email_with_paper_subject(self):
        response = self.client.post(self.url, self.payload, format="json")
        self.assertEqual(response.status_code, 200)
        sent = mail.outbox[0]
        self.assertEqual(sent.subject, "Working paper response: Decompose Now, Localize Later v0.9")
        self.assertEqual(sent.reply_to, ["ada@example.com"])
        self.assertIn("Correction", sent.body)
        self.assertIn("May be quoted or credited", sent.body)
        self.assertIn("Example Co", sent.body)

    def test_unknown_response_type_is_refused(self):
        response = self.client.post(self.url, {**self.payload, "response_type": "rant"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_credit_defaults_to_no(self):
        payload = {k: v for k, v in self.payload.items() if k != "may_credit"}
        self.client.post(self.url, payload, format="json")
        self.assertIn("Not for quoting or credit", mail.outbox[0].body)

    def test_honeypot_is_accepted_quietly_and_not_sent(self):
        response = self.client.post(self.url, {**self.payload, "website": "x"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
