# apps/profiles/services/profiles.py

from django.template.defaultfilters import slugify
from profiles.models import UserProfile

def ensure_user_profile(user) -> UserProfile:
    """
    Get or create a profile for the given user.
    Ensures a stable, unique slug.
    """
    prof, created = UserProfile.objects.get_or_create(user=user)
    # Minimal defaults (set once)
    if created:
        # display_name fallback
        full = f"{user.first_name} {user.last_name}".strip() or user.username
        prof.display_name = full

        # unique slug from name/username
        base = slugify(full) or slugify(user.username) or "user"
        slug = base
        i = 2
        while UserProfile.objects.filter(slug=slug).exclude(pk=prof.pk).exists():
            slug = f"{base}-{i}"
            i += 1
        prof.slug = slug
        prof.save(update_fields=["display_name", "slug"])
    return prof
