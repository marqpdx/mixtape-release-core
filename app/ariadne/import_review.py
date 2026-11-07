"""
Ariadne -- Cass to Crossroads result flow (build plan
puddlejump/decisions/ariadne/build-plan-cass-to-crossroads-result-flow.md
§3-4, §6 piece 2).

Writes an export package (`ariadne.export.build_review_export_package`)
into Crossroads' own database. Identity: every row is upserted by the id
it already carries from Cass (build plan §3) -- re-publishing the same
Review replaces its rows in place, nothing is duplicated.

Versions: Crossroads keeps the latest published Review only per Inquiry
(CTO decision, 2026-11-07, build plan §4) -- importing a Review does not
keep the row it supersedes. `superseded_review_id` is still carried in
the package and stored on the row, so lineage can be turned on later
without a schema change, even though nothing here surfaces it yet.
"""

from __future__ import annotations

from datetime import datetime

from django.db import transaction

from ariadne.models import CorpusSnapshot, Inquiry, InquiryReview, InquiryRun, InquiryTheme


class ReviewImportError(ValueError):
    pass


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _require(package: dict, *keys: str) -> dict:
    node = package
    for key in keys:
        if key not in node:
            raise ReviewImportError(f"Missing required field: {'.'.join(keys)}")
        node = node[key]
    return node


@transaction.atomic
def import_review_package(package: dict) -> InquiryReview:
    if package.get("schema_version") != 1:
        raise ReviewImportError(f"Unsupported schema_version: {package.get('schema_version')!r}")

    inquiry_data = _require(package, "inquiry")
    snapshot_data = _require(package, "corpus_snapshot")
    run_data = _require(package, "run")
    review_data = _require(package, "review")
    theme_rows = package.get("themes", [])

    inquiry, _ = Inquiry.objects.update_or_create(
        id=inquiry_data["id"],
        defaults={
            "question": inquiry_data["question"],
            "sub_questions": inquiry_data["sub_questions"],
            "status": inquiry_data["status"],
        },
    )

    snapshot, _ = CorpusSnapshot.objects.update_or_create(
        id=snapshot_data["id"],
        defaults={
            "manifest_hash": snapshot_data["manifest_hash"],
            "source_revision_ids": snapshot_data["source_revision_ids"],
            "captured_at": _parse_dt(snapshot_data["captured_at"]),
        },
    )

    run, _ = InquiryRun.objects.update_or_create(
        id=run_data["id"],
        defaults={
            "inquiry_id": inquiry.id,
            "corpus_snapshot_id": snapshot.id,
            "status": run_data["status"],
            "model_versions": run_data["model_versions"],
            "started_at": _parse_dt(run_data.get("started_at")),
            "completed_at": _parse_dt(run_data.get("completed_at")),
        },
    )

    for theme_data in theme_rows:
        InquiryTheme.objects.update_or_create(
            id=theme_data["id"],
            defaults={
                "run_id": run.id,
                "label": theme_data["label"],
                "label_source": theme_data["label_source"],
                "passage_ids": theme_data["passage_ids"],
                "rank": theme_data["rank"],
            },
        )

    review, _ = InquiryReview.objects.update_or_create(
        id=review_data["id"],
        defaults={
            "inquiry_id": inquiry.id,
            "run_id": run.id,
            "version": review_data["version"],
            "body_markdown": review_data["body_markdown"],
            "citations": review_data["citations"],
            "uncited_claim_count": review_data["uncited_claim_count"],
            "status": review_data["status"],
            "draft_calls": review_data["draft_calls"],
            "superseded_review_id": review_data.get("superseded_review_id"),
        },
    )

    # Latest-published-version-only (CTO, 2026-11-07): what Crossroads
    # *serves* for this Inquiry is whichever Review `standing_review`
    # points at -- repointing it here is what "latest-only" actually
    # means for a reader. The prior standing Review's row is left in
    # place rather than hard-deleted: `superseded_review` is a real
    # self-FK with on_delete=SET_NULL, so deleting the row it points to
    # would null that pointer at the database level and destroy the very
    # lineage the package carries it forward for (build plan §4's "so
    # lineage can be turned on later without a schema change" only holds
    # if the superseded row still exists to point at). Nothing on
    # Crossroads reads a non-standing Review, so this costs one orphaned
    # row per re-publish of the same Inquiry, not unbounded growth.
    inquiry.standing_review = review
    inquiry.save(update_fields=["standing_review", "updated_at"])

    return review
