from django.db import models


class GroupContext(models.Model):
    group = models.OneToOneField(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="context",
    )

    # Populated from OnboardingQuestion answers or direct console entry
    founding_story = models.TextField(blank=True)
    non_negotiables = models.JSONField(default=list)
    voice_description = models.TextField(blank=True)
    outward_feel = models.TextField(blank=True)

    context_health_score = models.IntegerField(default=0)  # 0–100, computed on save (Phase 3)
    last_prompted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Group Context"

    def __str__(self):
        return f"Context for {self.group}"
