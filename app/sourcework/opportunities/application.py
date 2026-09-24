from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
import subprocess
import tempfile

from django.conf import settings
from sourcework.models import OpportunityApplicationDraft, OpportunityProfile, ProvisionalData
from utils.writing.writing_utils import render_html_from_prosemirror


EMPTY_TIPTAP_DOCUMENT = {"type": "doc", "content": [{"type": "paragraph"}]}


def create_cover_letter_draft(
    *,
    opportunity: ProvisionalData,
    profile: OpportunityProfile,
    owner,
) -> OpportunityApplicationDraft:
    payload = opportunity.normalized_payload or {}
    context = _generation_context(opportunity=opportunity, profile=profile, owner=owner)
    draft, _ = OpportunityApplicationDraft.objects.update_or_create(
        owner_user=owner,
        opportunity=opportunity,
        defaults={
            "profile": profile,
            "resume_asset": profile.resume_asset,
            "status": "draft",
            "opportunity_title": str(payload.get("title") or ""),
            "recipient_name": str(payload.get("recruiter_name") or ""),
            "recipient_email": str(payload.get("contact_email") or ""),
            "letter_body": "",
            "letter_body_json": EMPTY_TIPTAP_DOCUMENT,
            "generation_context": context,
            "generated_by": "member",
            "generated_at": None,
        },
    )
    return draft


def render_cover_letter_pdf(*, draft: OpportunityApplicationDraft) -> bytes:
    markdown = _render_cover_letter_markdown(draft)
    puddlejump_root = getattr(settings, "PUDDLEJUMP_PATH", None)
    if not puddlejump_root:
        raise RuntimeError("Ledger PDF export is not configured on this server.")
    renderer = Path(str(puddlejump_root)).expanduser() / "zz" / "_ml" / "make-pdf.sh"
    if not renderer.is_file():
        raise RuntimeError(f"Ledger PDF renderer was not found at {renderer}.")

    with tempfile.TemporaryDirectory(prefix="mixtape-cover-letter-") as temp_dir:
        markdown_path = Path(temp_dir) / "cover-letter.md"
        pdf_path = markdown_path.with_suffix(".pdf")
        markdown_path.write_text(markdown, encoding="utf-8")
        try:
            result = subprocess.run(
                [str(renderer), str(markdown_path)],
                capture_output=True,
                check=False,
                text=True,
                timeout=90,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Ledger PDF export could not start: {exc}") from exc
        if result.returncode != 0 or not pdf_path.is_file():
            detail = (result.stderr or result.stdout or "unknown renderer failure").strip()
            raise RuntimeError(f"Ledger PDF export failed: {detail}")
        return pdf_path.read_bytes()


def _render_cover_letter_markdown(draft: OpportunityApplicationDraft) -> str:

    owner = draft.owner_user
    opportunity = draft.opportunity.normalized_payload or {}
    sender_name = owner.get_full_name().strip() or owner.username
    sender_email = owner.email or ""
    recipient = draft.recipient_name or "Hiring team"
    if draft.letter_body_json:
        body = render_html_from_prosemirror(draft.letter_body_json)
    else:
        body = f"<p>{escape(draft.letter_body).replace(chr(10), '<br>')}</p>"
    title = draft.opportunity_title.strip() or str(opportunity.get("title") or "Opportunity")
    organization = str(opportunity.get("organization") or "")
    document_title = f"Cover Letter — {title}"
    return (
        "---\n"
        f'title: "{_frontmatter_value(document_title)}"\n'
        f"date: {date.today().isoformat()}\n"
        "theme: Ledger\n"
        "---\n\n"
        f"# {escape(sender_name)}\n\n"
        f"{escape(sender_email)}  \n"
        f"**Application for {escape(title)}"
        f"{f' at {escape(organization)}' if organization else ''}**\n\n"
        "---\n\n"
        f"{date.today():%B %d, %Y}\n\n"
        f"{escape(recipient)}  \n"
        f"{escape(organization)}\n\n"
        f"**Re: {escape(title)}**\n\n"
        f"{body}\n\n"
        "Sincerely,  \n"
        f"{escape(sender_name)}\n"
    )


def _frontmatter_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _generation_context(*, opportunity: ProvisionalData, profile: OpportunityProfile, owner) -> dict:
    payload = opportunity.normalized_payload or {}
    return {
        "candidate": {
            "name": owner.get_full_name().strip() or owner.username,
            "target_roles": profile.target_roles,
            "seniority": profile.seniority,
            "strong_domains": profile.strong_domains,
            "strong_technologies": profile.strong_technologies,
            "resume_label": profile.resume_label,
            "resume_version": profile.resume_version,
            "resume_asset_id": str(profile.resume_asset_id) if profile.resume_asset_id else None,
            "resume_file_name": profile.resume_asset.file_name if profile.resume_asset_id else None,
        },
        "opportunity": {
            "title": payload.get("title"),
            "organization": payload.get("organization"),
            "description": payload.get("description"),
            "skills": payload.get("skills") or [],
            "matched_terms": (payload.get("preliminary_fit") or {}).get("matched_terms") or [],
        },
    }
