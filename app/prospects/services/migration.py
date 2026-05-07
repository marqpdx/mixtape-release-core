"""
EC-B10: ProspectToGroupMigrationService

Walks the ProspectQuestionOnboardingMap, finds the best available response
text for each mapped question across the prospect's submitted sessions, and
pre-populates the Group's GroupContext. Stamps converted_at on each migrated
ProspectResponse. Sets BusinessProspect.converted_to_group.

Phase 1 field routing (flat model):
  identity    → founding_story  (appended, line-separated)
  presentation → voice_description (appended)
  operations  → outward_feel    (appended)
  relationships / knowledge → skipped (Phase 1 scope)

The "non-negotiable" question maps to non_negotiables (JSONField, list of strings).
"""

from django.db import transaction
from django.utils import timezone


def _best_text(response):
    """Return the richest available text from a ProspectResponse."""
    return (
        response.human_refined_text
        or response.ai_summary_text
        or response.response_text
        or ""
    ).strip()


def _append_field(existing, new_text):
    if not new_text:
        return existing
    if existing:
        return f"{existing}\n\n{new_text}"
    return new_text


class ProspectToGroupMigrationService:

    @staticmethod
    @transaction.atomic
    def convert(prospect, group):
        """
        Migrate a BusinessProspect's intake responses into the Group's GroupContext.

        Args:
            prospect: BusinessProspect instance
            group: groups.Group instance the prospect is converting into

        Returns:
            dict with keys: group_context, migrated_count, skipped_count, detail
        """
        from groups.models import GroupContext
        from prospects.models import ProspectQuestionOnboardingMap, ProspectResponse

        # Get or create the GroupContext for this group
        group_context, _ = GroupContext.objects.get_or_create(group=group)

        # Gather all submitted responses for this prospect across all sessions,
        # keyed by question_id for fast lookup
        submitted_responses = (
            ProspectResponse.objects
            .filter(
                intake_session__prospect=prospect,
                intake_session__status="submitted",
            )
            .select_related("question")
            .order_by("-intake_session__submitted_at")  # latest session first
        )
        # Build {question_id: best_response} — latest session wins
        response_by_question = {}
        for resp in submitted_responses:
            qid = str(resp.question_id)
            if qid not in response_by_question:
                response_by_question[qid] = resp

        # Walk the map
        maps = (
            ProspectQuestionOnboardingMap.objects
            .select_related("prospect_question", "onboarding_question")
            .all()
        )

        migrated_count = 0
        skipped_count = 0
        detail = []
        to_stamp = []

        for entry in maps:
            qid = str(entry.prospect_question_id)
            response = response_by_question.get(qid)
            if not response:
                skipped_count += 1
                continue

            text = _best_text(response)
            if not text:
                skipped_count += 1
                continue

            oq = entry.onboarding_question
            category = oq.category
            question_text = oq.text.lower()

            # Route to the appropriate GroupContext field
            if "non-negotiable" in question_text or "non negotiable" in question_text:
                # Append as a list item if not already present
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                existing = group_context.non_negotiables or []
                for line in lines:
                    if line not in existing:
                        existing.append(line)
                group_context.non_negotiables = existing

            elif category == "identity":
                group_context.founding_story = _append_field(group_context.founding_story, text)

            elif category == "presentation":
                group_context.voice_description = _append_field(group_context.voice_description, text)

            elif category == "operations":
                group_context.outward_feel = _append_field(group_context.outward_feel, text)

            else:
                # relationships / knowledge — out of scope for Phase 1 flat model
                skipped_count += 1
                continue

            to_stamp.append(response)
            migrated_count += 1
            detail.append(
                f"[{oq.category}] {oq.text[:60]} → {text[:60]}"
            )

        group_context.save()

        # Stamp converted_at on each migrated response
        now = timezone.now()
        for resp in to_stamp:
            resp.converted_at = now
            resp.save(update_fields=["converted_at"])

        # Update the prospect FK and status
        prospect.converted_to_group = group
        prospect.status = "won"
        prospect.save(update_fields=["converted_to_group", "status", "updated_at"])

        return {
            "group_context_id": group_context.pk,
            "migrated_count": migrated_count,
            "skipped_count": skipped_count,
            "detail": detail,
        }
