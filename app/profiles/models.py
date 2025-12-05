import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.template.defaultfilters import slugify

from fundamentals.bases import BaseModel


class UserProfile(BaseModel):
    """
    Minimal user profile model for Phase 1.
    Represents public-facing member information (1:1 with User).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, unique=True)

    user = models.OneToOneField(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="profile"
    )

    slug = models.SlugField(unique=True, max_length=99)
    display_name = models.CharField(max_length=48, help_text="Your public facing screen name.")
    quick_intro = models.TextField(max_length=300, default="", blank=True, help_text="A quick bit about yourself.")

    # Placeholder for avatar/images (next phase - will use actual file storage)
    avatar_url = models.CharField(max_length=512, default="", blank=True, help_text="Avatar image URL")

    def save(self, *args, **kwargs):
        # Auto-generate slug from display_name or username
        if not self.slug:
            base = slugify(self.display_name or self.user.username)
            slug = base
            counter = 1
            while UserProfile.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Profile: {self.display_name} (@{self.user.username})"

    class Meta:
        app_label = "profiles"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
