from __future__ import annotations

from datetime import date
from html import escape
import json
import re

from django.utils import timezone

from inkwell.client import service_generate
from sourcework.models import OpportunityApplicationDraft, OpportunityProfile, ProvisionalData


LETTER_SCHEMA = {
    "type": "object",
    "properties": {
        "body": {"type": "string"},
    },
    "required": ["body"],
}


def generate_cover_letter_draft(
    *,
    opportunity: ProvisionalData,
    profile: OpportunityProfile,
    owner,
) -> OpportunityApplicationDraft:
    payload = opportunity.normalized_payload or {}
    context = _generation_context(opportunity=opportunity, profile=profile, owner=owner)
    result = service_generate(
        system_prompt=(
            "Draft a concise professional cover letter using only the supplied facts. "
            "Do not invent employers, projects, years of experience, credentials, or outcomes. "
            "Do not include addresses, a date, greeting, sign-off, or sender name; those are rendered separately. "
            "Return valid JSON only."
        ),
        prompt=(
            "Write three or four short paragraphs for this application. Explain the strongest grounded fit, "
            "acknowledge the specific role, and close with interest in a conversation.\n\n"
            f"Application facts:\n{json.dumps(context, indent=2, ensure_ascii=True)}"
        ),
        schema=LETTER_SCHEMA,
        max_tokens=700,
        temperature=0.2,
        timeout_seconds=120,
    )
    body = str((result.get("result") or {}).get("body") or "").strip()
    if not body:
        raise ValueError("Inkwell returned an empty cover-letter draft.")
    draft, _ = OpportunityApplicationDraft.objects.update_or_create(
        owner_user=owner,
        opportunity=opportunity,
        defaults={
            "profile": profile,
            "status": "draft",
            "recipient_name": str(payload.get("recruiter_name") or ""),
            "recipient_email": str(payload.get("contact_email") or ""),
            "letter_body": body,
            "generation_context": context,
            "generated_by": "inkwell",
            "generated_at": timezone.now(),
        },
    )
    return draft


def render_cover_letter_pdf(*, draft: OpportunityApplicationDraft) -> bytes:
    try:
        from weasyprint import CSS, HTML
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("WeasyPrint is required for cover-letter PDF export.") from exc

    owner = draft.owner_user
    opportunity = draft.opportunity.normalized_payload or {}
    sender_name = owner.get_full_name().strip() or owner.username
    sender_email = owner.email or ""
    recipient = draft.recipient_name or "Hiring team"
    paragraphs = "".join(
        f"<p>{escape(paragraph.strip()).replace(chr(10), '<br>')}</p>"
        for paragraph in re.split(r"\n\s*\n", draft.letter_body)
        if paragraph.strip()
    )
    document = (
        '<!doctype html><html><head><meta charset="utf-8"></head><body>'
        f'<header><strong>{escape(sender_name)}</strong><br>{escape(sender_email)}</header>'
        f'<p class="date">{date.today():%B %d, %Y}</p>'
        f'<p>{escape(recipient)}<br>{escape(str(opportunity.get("organization") or ""))}</p>'
        f'<p>Re: {escape(str(opportunity.get("title") or "Opportunity"))}</p>'
        f'<p>Dear {escape(recipient)},</p>{paragraphs}'
        f'<p>Sincerely,<br>{escape(sender_name)}</p>'
        "</body></html>"
    )
    styles = """
        @page { size: Letter; margin: 0.8in 0.85in; }
        body { color: #17202a; font-family: Georgia, 'Times New Roman', serif; font-size: 11pt; line-height: 1.48; }
        header { border-bottom: 1px solid #9aa4ad; margin-bottom: 22px; padding-bottom: 10px; }
        p { margin: 0 0 13px; }
        .date { margin-bottom: 20px; }
    """
    return HTML(string=document).write_pdf(stylesheets=[CSS(string=styles)])


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
        },
        "opportunity": {
            "title": payload.get("title"),
            "organization": payload.get("organization"),
            "description": payload.get("description"),
            "skills": payload.get("skills") or [],
            "matched_terms": (payload.get("preliminary_fit") or {}).get("matched_terms") or [],
        },
    }
