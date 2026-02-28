# spellbook/models.py
"""
Shared spell dictionary for writing tools.

This provides a platform-wide spell correction dictionary that:
- All authenticated users can read
- Superadmins can add/remove corrections directly
- All users can submit suggestions for review
"""

import uuid

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError


class SpellCorrection(models.Model):
    """
    Approved spell corrections - visible to all users.

    These are the canonical corrections used by the spell correction tool.
    Only superadmins can add/remove entries directly.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wrong_word = models.CharField(
        max_length=100,
        db_index=True,
        unique=True,
        help_text="The misspelled word (lowercase)",
    )
    correct_word = models.CharField(
        max_length=100,
        help_text="The correct spelling",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="spell_corrections_added",
        help_text="User who added this correction",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    usage_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times this correction has been applied",
    )

    class Meta:
        ordering = ["wrong_word"]
        verbose_name = "Spell Correction"
        verbose_name_plural = "Spell Corrections"

    def __str__(self):
        return f"{self.wrong_word} → {self.correct_word}"


class SpellSuggestion(models.Model):
    """
    User-submitted spell correction suggestions awaiting review.

    Any authenticated user can submit a suggestion.
    Superadmins review and approve/reject suggestions.
    Approved suggestions are converted to SpellCorrection entries.
    """

    STATUS_CHOICES = [
        ("pending", "Pending Review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wrong_word = models.CharField(
        max_length=100,
        db_index=True,
        help_text="The misspelled word",
    )
    correct_word = models.CharField(
        max_length=100,
        help_text="Suggested correct spelling",
    )
    suggested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="spell_suggestions",
        help_text="User who submitted this suggestion",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="spell_suggestions_reviewed",
        help_text="Superadmin who reviewed this suggestion",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(
        blank=True,
        help_text="Optional note from reviewer (e.g., reason for rejection)",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Spell Suggestion"
        verbose_name_plural = "Spell Suggestions"
        # Allow multiple suggestions for same word (from different users)
        # The review process handles duplicates

    def __str__(self):
        return f"{self.wrong_word} → {self.correct_word} ({self.status})"


class UserDictionaryEntry(models.Model):
    """User-scoped dictionary entries for ignore/replace behavior."""

    class Kind(models.TextChoices):
        IGNORE = "ignore", "Ignore"
        REPLACE = "replace", "Replace"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="spell_dictionary_entries",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    token = models.CharField(max_length=100, db_index=True)
    display = models.CharField(max_length=100, blank=True, default="")
    replacement = models.CharField(max_length=100, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="spell_dictionary_entries_created",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["token"]
        unique_together = [("owner_user", "kind", "token")]
        verbose_name = "User Dictionary Entry"
        verbose_name_plural = "User Dictionary Entries"

    def clean(self):
        if self.kind == self.Kind.REPLACE and not self.replacement:
            raise ValidationError({"replacement": "Replacement is required for replace entries."})
        if self.kind == self.Kind.IGNORE:
            self.replacement = ""

    def save(self, *args, **kwargs):
        self.token = self.token.lower().strip()
        if self.display:
            self.display = self.display.strip()
        if self.replacement:
            self.replacement = self.replacement.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.kind == self.Kind.REPLACE:
            return f"{self.owner_user_id}: {self.token} → {self.replacement}"
        return f"{self.owner_user_id}: ignore {self.token}"
