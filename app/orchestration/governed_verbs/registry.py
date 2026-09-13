from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AuthorityRequirement = Literal["superuser", "group_owner", "group_admin", "group_steward", "service"]
AuditBehavior = Literal["action_run", "domain_activity", "none"]
ConfirmationRequirement = Literal["always", "destructive_only", "never"]
Destructiveness = Literal["none", "low", "medium", "high"]
Reversibility = Literal["reversible", "partially_reversible", "irreversible"]


@dataclass(frozen=True)
class GovernedVerb:
    verb_id: str
    label: str
    domain: str
    description: str
    required_authority: AuthorityRequirement
    affected_shapes: tuple[str, ...]
    reversibility: Reversibility
    destructiveness: Destructiveness
    confirmation: ConfirmationRequirement
    audit_behavior: AuditBehavior


GOVERNED_VERBS: tuple[GovernedVerb, ...] = (
    GovernedVerb(
        verb_id="crossroads.group.inspect",
        label="Inspect group",
        domain="groups",
        description="Read the current state of a Crossroads group before planning changes.",
        required_authority="group_admin",
        affected_shapes=("crossroads.group",),
        reversibility="reversible",
        destructiveness="none",
        confirmation="never",
        audit_behavior="none",
    ),
    GovernedVerb(
        verb_id="crossroads.group.create_or_update",
        label="Create or update group",
        domain="groups",
        description="Create an ordinary group or bring an existing group into the requested shape.",
        required_authority="superuser",
        affected_shapes=("crossroads.group",),
        reversibility="partially_reversible",
        destructiveness="low",
        confirmation="always",
        audit_behavior="action_run",
    ),
    GovernedVerb(
        verb_id="crossroads.group.assign_admin",
        label="Assign group admin",
        domain="groups",
        description="Ensure a user has administrative stewardship for a group.",
        required_authority="superuser",
        affected_shapes=("crossroads.group", "crossroads.group_membership"),
        reversibility="partially_reversible",
        destructiveness="low",
        confirmation="always",
        audit_behavior="action_run",
    ),
    GovernedVerb(
        verb_id="earthlab.course.inspect",
        label="Inspect EarthLab course",
        domain="earthlab",
        description="Read current course, lesson, item, and run state for an Install plan.",
        required_authority="group_steward",
        affected_shapes=("earthlab.course", "earthlab.lesson", "earthlab.course_run"),
        reversibility="reversible",
        destructiveness="none",
        confirmation="never",
        audit_behavior="none",
    ),
    GovernedVerb(
        verb_id="earthlab.course.create_or_update",
        label="Create or update EarthLab course",
        domain="earthlab",
        description="Create or update a course, its lessons, ordered course items, and pilot run.",
        required_authority="superuser",
        affected_shapes=("earthlab.course", "earthlab.lesson", "earthlab.course_item", "earthlab.course_run"),
        reversibility="partially_reversible",
        destructiveness="low",
        confirmation="always",
        audit_behavior="action_run",
    ),
    GovernedVerb(
        verb_id="threadworks.forum.inspect",
        label="Inspect Threadworks forum",
        domain="threadworks",
        description="Read current forum and discussion state for an Install plan.",
        required_authority="group_steward",
        affected_shapes=("threadworks.forum", "threadworks.discussion"),
        reversibility="reversible",
        destructiveness="none",
        confirmation="never",
        audit_behavior="none",
    ),
    GovernedVerb(
        verb_id="threadworks.forum.create_or_update",
        label="Create or update Threadworks forum",
        domain="threadworks",
        description="Create or update a group forum and its initial discussions.",
        required_authority="superuser",
        affected_shapes=("threadworks.forum", "threadworks.discussion"),
        reversibility="partially_reversible",
        destructiveness="low",
        confirmation="always",
        audit_behavior="action_run",
    ),
    GovernedVerb(
        verb_id="group_landing.inspect",
        label="Inspect group landing page",
        domain="groups",
        description="Read the public landing configuration before proposing or applying changes.",
        required_authority="group_steward",
        affected_shapes=("crossroads.group_public_config", "crossroads.public_page"),
        reversibility="reversible",
        destructiveness="none",
        confirmation="never",
        audit_behavior="none",
    ),
    GovernedVerb(
        verb_id="group_landing.summarize_welcome_from_document",
        label="Summarize welcome from document",
        domain="groups",
        description="Produce a proposed welcome summary from source content without mutating group state.",
        required_authority="group_steward",
        affected_shapes=("crossroads.group_public_config", "document.summary"),
        reversibility="reversible",
        destructiveness="none",
        confirmation="never",
        audit_behavior="action_run",
    ),
    GovernedVerb(
        verb_id="group_landing.amend",
        label="Amend group landing page",
        domain="groups",
        description="Apply approved welcome, hero, or orientation copy to the group landing surface.",
        required_authority="superuser",
        affected_shapes=("crossroads.group_public_config", "crossroads.public_page"),
        reversibility="partially_reversible",
        destructiveness="low",
        confirmation="always",
        audit_behavior="action_run",
    ),
    GovernedVerb(
        verb_id="install.publish",
        label="Publish Install specimen",
        domain="orchestration",
        description="Execute an approved Install plan as a visible sequence of governed verbs.",
        required_authority="superuser",
        affected_shapes=("orchestration.install_specimen",),
        reversibility="partially_reversible",
        destructiveness="low",
        confirmation="always",
        audit_behavior="action_run",
    ),
)


def get_governed_verb(verb_id: str) -> GovernedVerb:
    for verb in GOVERNED_VERBS:
        if verb.verb_id == verb_id:
            return verb
    raise KeyError(f"Unknown governed verb: {verb_id}")
