# atrium/ai/context.py
#
# BerylPersonalContextBuilder — assembles personal context for Atrium dispatch.
#
# Sources (v1):
#   - UserProfile fields: display_name, practice_area, quick_intro, skills,
#     work_areas, who_are_you, why_are_you_here
#   - Recent AtriumSession titles (last 5, excluding current session)
#
# The built context is appended after session_context in the system prompt.
# A preview is surfaced to the member via GET /api/atrium/sessions/<id>/context/.


class BerylPersonalContextBuilder:

    RECENT_SESSION_LIMIT = 5

    def build(self, session) -> str:
        """Return synthesized personal context string, empty string if nothing to add."""
        profile = session.member
        lines = []

        name = profile.display_name or profile.user.username
        lines.append(f"Member: {name}")

        if profile.practice_area:
            lines.append(f"Practice area: {profile.practice_area}")

        if profile.quick_intro:
            lines.append(f"About: {profile.quick_intro}")

        if profile.skills:
            lines.append(f"Skills: {profile.skills}")

        if profile.work_areas:
            lines.append(f"Work areas: {profile.work_areas}")

        if profile.who_are_you:
            lines.append(f"Self-description: {profile.who_are_you}")

        if profile.why_are_you_here:
            lines.append(f"Goals: {profile.why_are_you_here}")

        recent_titles = self._recent_session_titles(session)
        if recent_titles:
            lines.append(f"Recent sessions: {', '.join(recent_titles)}")

        # Always at least the member name, so always non-empty
        return "\n".join(lines)

    def sources(self, session) -> list[str]:
        """Human-readable list of context sources included in this build."""
        src = ["member profile"]
        if self._recent_session_titles(session):
            src.append("recent sessions")
        return src

    def _recent_session_titles(self, session) -> list[str]:
        from atrium.models import AtriumSession
        recent = (
            AtriumSession.objects
            .filter(member=session.member, deleted_at__isnull=True)
            .exclude(id=session.id)
            .order_by("-last_activity_at", "-created_at")
            .values_list("title", flat=True)[: self.RECENT_SESSION_LIMIT]
        )
        return [t for t in recent if t]
