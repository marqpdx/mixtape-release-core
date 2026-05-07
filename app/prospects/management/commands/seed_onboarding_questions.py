"""
EC-B8: Seed OnboardingQuestion records from the canonical question bank.

Idempotent — skips questions that already exist by exact text match.
Questions are admin-editable after seeding; re-running only adds missing ones.

Usage:
    python manage.py seed_onboarding_questions
"""

from django.core.management.base import BaseCommand

from prospects.models import OnboardingQuestion


QUESTION_BANK = [
    # ── Identity & Founding ──────────────────────────────────────────────────
    {
        "category": "identity",
        "order": 1,
        "text": "Why did you start this enterprise?",
        "triggers_persona_creation": False,
    },
    {
        "category": "identity",
        "order": 2,
        "text": "What does success look like for you in three years?",
        "triggers_persona_creation": False,
    },
    {
        "category": "identity",
        "order": 3,
        "text": "What three things are non-negotiable about how you operate?",
        "triggers_persona_creation": False,
    },
    {
        "category": "identity",
        "order": 4,
        "text": "What are you not? (Often more revealing than what you are.)",
        "triggers_persona_creation": False,
    },

    # ── Outward Presentation ─────────────────────────────────────────────────
    {
        "category": "presentation",
        "order": 1,
        "text": "How do you want people to feel when they encounter your brand?",
        "triggers_persona_creation": False,
    },
    {
        "category": "presentation",
        "order": 2,
        "text": "How would you describe your voice — formal or casual, warm or direct, serious or playful?",
        "triggers_persona_creation": False,
    },
    {
        "category": "presentation",
        "order": 3,
        "text": "What's an example of communication you've sent that felt exactly right?",
        "triggers_persona_creation": False,
    },

    # ── Operational Character ────────────────────────────────────────────────
    {
        "category": "operations",
        "order": 1,
        "text": "What does a good week look like for this enterprise?",
        "triggers_persona_creation": False,
    },
    {
        "category": "operations",
        "order": 2,
        "text": "Where does most of your energy go right now?",
        "triggers_persona_creation": False,
    },
    {
        "category": "operations",
        "order": 3,
        "text": "What keeps falling through the cracks?",
        "triggers_persona_creation": False,
    },
    {
        "category": "operations",
        "order": 4,
        "text": "What do you find yourself explaining over and over again?",
        "triggers_persona_creation": False,
    },

    # ── Relationships ────────────────────────────────────────────────────────
    {
        "category": "relationships",
        "order": 1,
        "text": "Who are your most important external relationships — customers, suppliers, partners?",
        "triggers_persona_creation": False,
    },
    {
        "category": "relationships",
        "order": 2,
        "text": "How do you communicate with them? What's the tone, what's the frequency?",
        "triggers_persona_creation": False,
    },
    {
        "category": "relationships",
        "order": 3,
        "text": "Are there relationships that need more attention than they currently get?",
        "triggers_persona_creation": False,
    },

    # ── Knowledge & People ───────────────────────────────────────────────────
    {
        "category": "knowledge",
        "order": 1,
        "text": "Who are the key people in your operation, and what do they own?",
        "triggers_persona_creation": False,
    },
    {
        "category": "knowledge",
        "order": 2,
        "text": "What knowledge exists only in someone's head right now?",
        "triggers_persona_creation": True,  # natural persona creation prompt
    },
    {
        "category": "knowledge",
        "order": 3,
        "text": "If a key person left tomorrow, what would be hardest to replace?",
        "triggers_persona_creation": False,
    },
]


class Command(BaseCommand):
    help = "Seed OnboardingQuestion records from the canonical question bank (EC-B8). Idempotent."

    def handle(self, *args, **options):
        created = 0
        skipped = 0

        for entry in QUESTION_BANK:
            _, was_created = OnboardingQuestion.objects.get_or_create(
                text=entry["text"],
                defaults={
                    "category": entry["category"],
                    "order": entry["order"],
                    "triggers_persona_creation": entry["triggers_persona_creation"],
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"OnboardingQuestion seed complete: {created} created, {skipped} already existed."
            )
        )
