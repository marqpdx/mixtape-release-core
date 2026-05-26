# groups/models/dec_enums.py

"""
Enums for the Groups Decorator System.
All enum definitions in one place for easy reference.
"""

from django.db import models


class DecoratorCategory(models.TextChoices):
    """Categories for both Group and Membership decorators."""
    IDENTITY = "identity", "Identity"
    CAPABILITY = "capability", "Capability"
    POLICY = "policy", "Policy"


class DispatchPolicy(models.TextChoices):
    CLOUD_DEFAULT = "cloud_default", "Cloud-assisted (default)"
    LOCAL_PREFERRED = "local_preferred", "Local-first (approve before cloud)"
    LOCAL_ONLY = "local_only", "Local only (regulated mode)"
    LOCAL_STRICT = "local_strict", "Strict local (no cloud, ever)"


class LocalModelTier(models.TextChoices):
    STANDARD = "standard", "Standard (Mistral 7B)"
    HIGH = "high", "High (Llama 3 70B)"


class GroupType(models.TextChoices):
    """Four core group types in the Mixtape ecosystem."""
    PERSONA = "persona", "Persona"
    CIRCLE = "circle", "Circle"
    COMMUNITY = "community", "Community"
    COALITION = "coalition", "Coalition"


class AssignmentSource(models.TextChoices):
    """How a decorator was assigned to a group or membership."""
    MANUAL = "manual", "Manual Assignment"
    PROFILE = "profile", "Applied via Profile"
    SYSTEM = "system", "System Assigned"


class GroupVisibility(models.TextChoices):
    """Visibility settings for groups."""
    PUBLIC = "public", "Public"
    PRIVATE = "private", "Private"
    UNLISTED = "unlisted", "Unlisted"


class AdmissionPolicy(models.TextChoices):
    """Admission policies for groups."""
    OPEN = "open", "Open to All"
    OPEN_PARENT_MEMBERS = "open_parent_members", "Open to Parent Group Members"
    APPLICATION = "application", "Application Required"
    APPLICATION_PARENT_MEMBERS = "application_parent_members", "Application from Parent Members"
    INVITE_ONLY = "invite_only", "Invite Only"
    CLOSED = "closed", "Closed"


class GovernanceModel(models.TextChoices):
    """Governance models for Coalition groups."""
    CONSENSUS = "consensus", "Consensus"
    MAJORITY = "majority", "Majority Vote"
    REPRESENTATIVE = "representative", "Representative"
    DELEGATED = "delegated", "Delegated Authority"


class MeetingFrequency(models.TextChoices):
    """Meeting frequency for Circle groups."""
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    BIWEEKLY = "biweekly", "Bi-Weekly"
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    ADHOC = "adhoc", "Ad-Hoc"


class PrivacyLevel(models.TextChoices):
    """Privacy levels for Persona groups."""
    PUBLIC = "public", "Public"
    MEMBERS = "members", "Members Only"
    FRIENDS = "friends", "Friends Only"


# Core roles that can be in the roles ArrayField
CORE_ROLES = ["member", "steward", "admin", "owner"]


def is_owner(roles: list[str]) -> bool:
    """Check if roles list contains owner role."""
    return "owner" in roles


def is_admin(roles: list[str]) -> bool:
    """
    Check if roles list contains admin role.

    Args:
        roles: List of role strings

    Returns:
        True if 'admin' is in the roles list
    """
    return "admin" in roles


def is_steward(roles: list[str]) -> bool:
    """
    Check if roles list contains steward role.

    Args:
        roles: List of role strings

    Returns:
        True if 'steward' is in the roles list
    """
    return "steward" in roles


def highest_role(roles: list[str]) -> str:
    """
    Get the highest role from a list of roles.

    Args:
        roles: List of role strings

    Returns:
        'owner', 'admin', 'steward', or 'member' based on hierarchy
    """
    if "owner" in roles:
        return "owner"
    if "admin" in roles:
        return "admin"
    if "steward" in roles:
        return "steward"
    return "member"
