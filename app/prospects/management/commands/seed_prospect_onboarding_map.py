"""
EC-B9: Seed ProspectQuestionOnboardingMap for shared questions.

Maps existing ProspectQuestion records to their corresponding OnboardingQuestion
records by prompt-text matching. At conversion time the migration service walks
this map to pre-populate GroupContext from intake responses.

Idempotent — skips mappings that already exist.
Requires EC-B8 (seed_onboarding_questions) to have run first.

Usage:
    python manage.py seed_prospect_onboarding_map
"""

from django.core.management.base import BaseCommand

from prospects.models import OnboardingQuestion, ProspectQuestion, ProspectQuestionOnboardingMap


# Each entry: (prospect_question_prompt_substring, onboarding_question_text_substring)
# Matched with icontains so minor wording drifts don't break the seed.
MAPPINGS = [
    (
        "Why do you do this work?",
        "Why did you start this enterprise?",
    ),
    (
        "Where do you feel friction or waste?",
        "What keeps falling through the cracks?",
    ),
    (
        "Where do you want to grow or improve?",
        "What does success look like for you in three years?",
    ),
]


class Command(BaseCommand):
    help = "Seed ProspectQuestionOnboardingMap entries for shared questions (EC-B9). Idempotent."

    def handle(self, *args, **options):
        created = 0
        skipped = 0
        missed = 0

        for pq_prompt, oq_text in MAPPINGS:
            pq = ProspectQuestion.objects.filter(prompt__icontains=pq_prompt.split("?")[0]).first()
            oq = OnboardingQuestion.objects.filter(text__icontains=oq_text.split("?")[0]).first()

            if not pq:
                self.stdout.write(self.style.WARNING(f"ProspectQuestion not found for: {pq_prompt!r}"))
                missed += 1
                continue

            if not oq:
                self.stdout.write(self.style.WARNING(f"OnboardingQuestion not found for: {oq_text!r}"))
                missed += 1
                continue

            _, was_created = ProspectQuestionOnboardingMap.objects.get_or_create(
                prospect_question=pq,
                defaults={"onboarding_question": oq},
            )
            if was_created:
                created += 1
                self.stdout.write(f"  Mapped: [{pq.order_index}] {pq.prompt[:60]} → {oq.text[:60]}")
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Map seed complete: {created} created, {skipped} already existed, {missed} not found."
            )
        )
