# mixtape/management/commands/bootstrap_mixtape.py

import getpass
import os
import sys

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from feedback.models import FeedbackBeacon
from groups.services.memberships import ensure_user_membership
from mixtape.services.defaults import ensure_default_group
from profiles.services.profiles import ensure_user_profile


User = get_user_model()


class Command(BaseCommand):
    help = (
        "Bootstrap Mixtape platform with superuser, default group (with polymorphic sponsor), "
        "and initial memberships."
    )

    # ---- Superuser helpers ----
    def _get_or_create_superuser_dev(self):
        # DEV-ONLY defaults; do not print password
        username = "admin"
        email = "marqpdx@gmail.com"
        password = "boston99"

        su = User.objects.filter(is_superuser=True).first()
        if su:
            self.stdout.write(f"Superuser exists: {su.username}")
            return su

        try:
            su = User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
                first_name="Admin",
                last_name="User",
            )
        except IntegrityError:
            su = User.objects.filter(username=username).first() or User.objects.filter(is_superuser=True).first()

        self.stdout.write(self.style.SUCCESS(f"✓ Created dev superuser: {su.username}"))
        return su

    def ensure_superuser_interactive_password(self):
        # Read fixed username/email from env; prompt only for password
        su = User.objects.filter(is_superuser=True).first()
        if su:
            self.stdout.write(f"Superuser exists: {su.username}")
            return su

        u = os.getenv("DJANGO_SUPERUSER_USERNAME", "admin")
        e = os.getenv("DJANGO_SUPERUSER_EMAIL", "marqpdx@gmail.com")

        if not u or not e:
            self.stderr.write(self.style.ERROR(
                "Missing DJANGO_SUPERUSER_USERNAME and/or DJANGO_SUPERUSER_EMAIL in environment."
            ))
            sys.exit(1)

        if not sys.stdin.isatty():
            self.stderr.write(self.style.ERROR(
                "No TTY detected. Set DJANGO_SUPERUSER_PASSWORD in env or run interactively."
            ))
            sys.exit(1)

        p = getpass.getpass(f"Set password for superuser '{u}': ")

        try:
            su = User.objects.create_superuser(
                username=u, email=e, password=p, first_name="Admin", last_name="User"
            )
        except IntegrityError:
            # In case a parallel process created it
            su = User.objects.filter(username=u).first() or User.objects.filter(is_superuser=True).first()

        self.stdout.write(self.style.SUCCESS(f"✓ Created superuser: {su.username}"))
        return su

    def handle(self, *args, **opts):
        # ---- Superuser creation OUTSIDE atomic to avoid holding a transaction while prompting ----
        if settings.DEBUG:
            self.stdout.write(self.style.WARNING("BOOTSTRAP IN DEBUG MODE"))
            su = self._get_or_create_superuser_dev()
        else:
            su = self.ensure_superuser_interactive_password()

        self.stdout.write(self.style.SUCCESS(f"Superuser: {su.username} ({su.pk})"))

        # ---- Everything else can be atomic ----
        with transaction.atomic():
            # 2. Create user profile
            su_profile = ensure_user_profile(su)
            self.stdout.write(self.style.SUCCESS(f"✓ Superuser profile: {su_profile.slug}"))

            # 3. Default group with polymorphic sponsor
            default_group = ensure_default_group(sponsor_user=su)
            self.stdout.write(self.style.SUCCESS(
                f"✓ Default group: {default_group.title} (id={default_group.pk})"
            ))
            self.stdout.write(self.style.SUCCESS(
                f"  ├─ Sponsor: {default_group.sponsor_display} (type={default_group.sponsor_type})"
            ))
            self.stdout.write(self.style.SUCCESS(
                f"  └─ Author: {default_group.author_display}"
            ))

            # 4. Membership
            ensure_user_membership(default_group, su, role="admin", is_active=True)
            self.stdout.write(self.style.SUCCESS("✓ Superuser membership: admin role"))

            # 5. Lighthouse feedback beacon
            FeedbackBeacon.objects.update_or_create(
                key="lighthouse",
                defaults={
                    "title": "Lighthouse Feedback",
                    "body_markdown": "Share bugs, ideas, or reactions with the team.",
                    "scope": FeedbackBeacon.Scope.GLOBAL,
                    "is_active": True,
                },
            )
            self.stdout.write(self.style.SUCCESS("✓ Lighthouse feedback beacon seeded"))

        self.stdout.write(self.style.SUCCESS("\n🎉 Bootstrap complete!"))
