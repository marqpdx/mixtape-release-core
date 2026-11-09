# surfaces/models.py
#
# ADR-0064 (Surface profiles, ratified 2026-11-09): a Surface that carries an
# agent has a Surface profile — one record, as data, holding the agent's
# persona, its write grant, its consent rule, who may enter, and where its
# agent runs. A new Surface of this kind is a new row and its charter grants,
# never a new code path (D1). Granted tools are NOT stored here: they live in
# core's tools/data-routes.toml (R4's tracked table), which is the
# CTO-approved, CI-checked source of truth, so a tool grant lives in exactly
# one reviewed place.

from fundamentals.bases import BaseModel
from django.db import models


class SurfaceKind(models.TextChoices):
    """D8: a Surface profile says where its agent runs; it is a setting,
    not a code path."""
    MEMBER = "member", "Member Surface"
    BUILDER = "builder", "Builder Surface"


class AgentHost(models.TextChoices):
    CROSSROADS = "crossroads", "Crossroads (production)"
    CASS = "cass", "Cassiopeia-A (development)"


class WhoMayEnter(models.TextChoices):
    """D8's 'who enters' column — a sponsor rule, decided per profile, not
    derived from kind (a future profile could differ)."""
    MEMBERS = "members", "Members"
    BUILDERS = "builders", "Builders only (the Argus Team, superusers)"


class WriteGrant(models.TextChoices):
    """R3's write-grant ladder (charter-amendment-surface-profiles.md §2).
    No Surface is an exception; each holds exactly one rung."""
    NONE = "none", "None"
    OWN_RECORDS = "own_records", "Own records"
    PROPOSE = "propose", "Propose"
    CANON_WRITER = "canon_writer", "Canon writer"


class ConsentRule(models.TextChoices):
    """D9: the consent is the session. A Member Surface's Dialogue starts with
    a press, same as any Atrium turn; a Builder Surface that runs scheduled
    work does so under a run series, whose record is the consent."""
    PRESS_EACH_TIME = "press_each_time", "Starts with a press, each time"
    RUN_SERIES = "run_series", "Governed by a run series (D9)"


class SurfaceProfile(BaseModel):
    """
    One record per Surface that carries an agent (D1). Six rows exist at
    ratification: Atrium, Catalyst, Writing (member); Argus, Puddlejump,
    SysAdmin (builder) — see ADR-0064 D8. `slug` is the fixed marker code
    looks up by; never match on `name` or display text.
    """

    slug = models.SlugField(
        max_length=40,
        unique=True,
        help_text="Fixed marker. Code looks up a Surface profile by this, never by name.",
    )
    name = models.CharField(max_length=80)
    persona = models.TextField(
        blank=True,
        default="",
        help_text="The agent's persona/system-prompt framing for this Surface.",
    )
    kind = models.CharField(max_length=10, choices=SurfaceKind.choices)
    agent_host = models.CharField(max_length=12, choices=AgentHost.choices)
    who_may_enter = models.CharField(max_length=10, choices=WhoMayEnter.choices)
    write_grant = models.CharField(
        max_length=14,
        choices=WriteGrant.choices,
        default=WriteGrant.NONE,
    )
    consent_rule = models.CharField(max_length=20, choices=ConsentRule.choices)

    class Meta(BaseModel.Meta):
        verbose_name = "Surface profile"
        verbose_name_plural = "Surface profiles"
        ordering = ["slug"]

    def __str__(self):
        return self.name
