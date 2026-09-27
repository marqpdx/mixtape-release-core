"""Canonical Claude Code generation for reviewed LinkedIn introductions."""

from __future__ import annotations

import json
import re

from claude import service as claude_service


GENERATION_PROMPT = """\
You are generating a LinkedIn synopsis for a published article from the Crossroads / Mindful Brilliance ecosystem.

Use only the article text supplied in this prompt. Do not use tools, inspect files,
search for external context, or draw on unrelated project memory.

Your task is not to summarize mechanically. Your task is to create a short LinkedIn-ready bridge artifact that introduces the article in a way that is:

- faithful to the article's real argument
- clear and readable on LinkedIn
- personable, intelligent, and grounded
- trustworthy rather than hype-driven
- reflective of a builder/operator who has done the work
- aligned with a humane, coherent, accountability-centered software ethos

The synopsis should sound like it was written by a thoughtful practitioner, not a content marketer.

## Audience
Assume the reader is one of:
- a recruiter
- a technical leader
- a founder
- a product person
- a thoughtful generalist interested in how software work is changing

They are intelligent but busy.

## What the synopsis should do
1. Identify the central shift, tension, or insight in the piece
2. Make the reader care in the first 1-2 lines
3. Remain faithful to the piece rather than overselling it
4. Invite click-through to the full article naturally

## Tone
Calm, lucid, slightly warm, credible, practical, human.

Avoid: hype, startup buzzwords, inflated claims, "game-changing", "revolutionary", "unlock", "leverage", generic inspiration, excessive abstraction, emoji, hashtags, sales language.

## Writing constraints
- Preserve the article's actual meaning
- Prefer concrete shifts over vague summaries
- If the article names a changed bottleneck, role, risk, or pattern, foreground that
- Do not invent claims not present in the article
- Do not flatten the piece into bland professionalism
- Do not mention Crossroads or Mindful Brilliance unless the article is explicitly about them
- Do not include a URL
- Do not write "In this article..." or "This piece explores..."
- Do not write in a corporate brand voice

Before writing, silently identify:
- the article's core claim
- the human stake
- the most LinkedIn-effective opening contrast

## Output format
Return ONLY valid JSON with these exact keys:
{{
  "hook": "<1-3 sentence hook, 180-320 characters>",
  "short_synopsis": "<fuller version for LinkedIn post intro, 350-700 characters>",
  "one_line_takeaway": "<single sentence, the deepest shift or claim>",
  "alt_hook": "<second hook version, slightly more direct and concrete>",
  "source_claim": "<internal: the article's core claim in one sentence>",
  "human_stake": "<internal: what is at stake for the reader/practitioner>"
}}

## Article
Title: {title}
Excerpt: {excerpt}
Opening: {body_preview}
"""


VALIDATION_PROMPT = """\
Review this LinkedIn synopsis draft for an article.

Use only the article excerpt and draft supplied in this prompt. Do not use tools,
inspect files, search for external context, or draw on unrelated project memory.

Article title: {title}
Article excerpt: {excerpt}

Synopsis draft:
{draft}

Check whether the synopsis is:
- faithful to the source article (does not invent claims)
- concrete rather than vague
- readable on LinkedIn
- credible and human-sounding
- free of hype, jargon, and overstatement

Reject or revise if it:
- sounds like marketing copy
- invents claims not in the article
- becomes generic commentary
- loses the article's actual tension or argument
- uses "game-changing", "revolutionary", "unlock", "leverage", or similar
- starts with "In this article..." or "This piece explores..."

If the draft is good, return it unchanged. If weak, revise.

Return ONLY valid JSON with the same keys as the input:
{{
  "hook": "<revised or unchanged>",
  "short_synopsis": "<revised or unchanged>",
  "one_line_takeaway": "<revised or unchanged>",
  "alt_hook": "<revised or unchanged>",
  "source_claim": "<unchanged>",
  "human_stake": "<unchanged>"
}}
"""


RESULT_KEYS = (
    "hook",
    "short_synopsis",
    "one_line_takeaway",
    "alt_hook",
    "source_claim",
    "human_stake",
)


class LinkedInCopyGenerationError(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    candidate = (text or "").strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", candidate)
        if not match:
            raise LinkedInCopyGenerationError("Claude Code returned no JSON object.")
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError as exc:
            raise LinkedInCopyGenerationError("Claude Code returned invalid JSON.") from exc

    if not isinstance(parsed, dict):
        raise LinkedInCopyGenerationError("Claude Code returned a non-object JSON value.")
    return parsed


def _normalize_result(result: dict) -> dict:
    normalized = {key: str(result.get(key) or "").strip() for key in RESULT_KEYS}
    if not normalized["hook"] or not normalized["short_synopsis"]:
        raise LinkedInCopyGenerationError("Claude Code omitted required LinkedIn copy fields.")
    normalized["model_used"] = "anthropic-claude-code"
    normalized["refused"] = False
    return normalized


def generate_linkedin_copy(
    *,
    action_run_id: str,
    title: str,
    excerpt: str,
    body_preview: str,
    cwd: str,
    run_as_user: str | None = None,
    timeout: int = 180,
) -> dict:
    """Run generation and review in one bounded, short-lived Claude session."""
    session_id = f"linkedin-copy:{action_run_id}"
    generation_prompt = GENERATION_PROMPT.format(
        title=title or "(untitled)",
        excerpt=excerpt or "(no excerpt)",
        body_preview=body_preview or "(no preview)",
    )

    try:
        generation_text = claude_service.run_session_blocking(
            session_id,
            generation_prompt,
            cwd,
            run_as_user=run_as_user,
            timeout=timeout,
        )
        if not generation_text:
            raise LinkedInCopyGenerationError("Claude Code generation returned no output.")
        draft = _extract_json(generation_text)

        validation_prompt = VALIDATION_PROMPT.format(
            title=title or "(untitled)",
            excerpt=excerpt or "(no excerpt)",
            draft=json.dumps(draft, indent=2),
        )
        validation_text = claude_service.run_session_blocking(
            session_id,
            validation_prompt,
            cwd,
            run_as_user=run_as_user,
            timeout=timeout,
        )
        if not validation_text:
            raise LinkedInCopyGenerationError("Claude Code review returned no output.")
        return _normalize_result(_extract_json(validation_text))
    finally:
        claude_service.terminate_session(session_id)
