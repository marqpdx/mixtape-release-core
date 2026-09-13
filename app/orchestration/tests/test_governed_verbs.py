from django.test import SimpleTestCase

from orchestration.governed_verbs import GOVERNED_VERBS, get_governed_verb


class GovernedVerbRegistryTests(SimpleTestCase):
    def test_registry_has_unique_verb_ids(self):
        verb_ids = [verb.verb_id for verb in GOVERNED_VERBS]

        self.assertEqual(len(verb_ids), len(set(verb_ids)))

    def test_recruiter_install_core_verbs_are_registered(self):
        expected = {
            "crossroads.group.create_or_update",
            "crossroads.group.assign_admin",
            "earthlab.course.create_or_update",
            "threadworks.forum.create_or_update",
            "group_landing.summarize_welcome_from_document",
            "group_landing.amend",
            "install.publish",
        }

        self.assertTrue(expected.issubset({verb.verb_id for verb in GOVERNED_VERBS}))

    def test_mutating_verbs_require_confirmation_and_audit(self):
        mutating_verbs = [
            verb for verb in GOVERNED_VERBS
            if verb.destructiveness != "none" or verb.reversibility != "reversible"
        ]

        self.assertGreater(len(mutating_verbs), 0)
        for verb in mutating_verbs:
            self.assertEqual(verb.confirmation, "always", verb.verb_id)
            self.assertEqual(verb.audit_behavior, "action_run", verb.verb_id)

    def test_get_governed_verb_returns_registered_verb(self):
        verb = get_governed_verb("earthlab.course.create_or_update")

        self.assertEqual(verb.domain, "earthlab")
