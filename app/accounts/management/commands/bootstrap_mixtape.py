# mixtape/management/commands/bootstrap_mixtape.py

import os, sys, getpass
from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError
from django.contrib.auth import get_user_model
from django.conf import settings

from groups.services.memberships import ensure_user_membership
from mixtape.services.defaults import ensure_default_group
# from identity.management.commands.seed_emblem_avatar_types import seed_emblem_types
# from identity.management.commands.seed_public_emblems import seed_public_emblems
# from identity.services.emblems import ensure_default_group_emblem, ensure_default_user_avatar
from profiles.services.profiles import ensure_user_profile


User = get_user_model()


class Command(BaseCommand):
    help = "Initialize Mixtape: superuser (if needed), default group, types, default emblem."

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
            # 2. Seed emblem TYPES first
            # types_created = seed_emblem_types() or 0
            # self.stdout.write(self.style.SUCCESS(f"Created {types_created} emblem types"))

            # 3. Create user profile + avatar
            su_profile = ensure_user_profile(su)
            # ensure_default_user_avatar(su_profile)
            self.stdout.write(self.style.SUCCESS(f"Superuser profile ready: {su_profile.slug} (avatar set)"))

            # 4. Default group + emblem
            default_group = ensure_default_group(sponsor_user=su)
            # ensure_default_group_emblem(default_group)
            self.stdout.write(self.style.SUCCESS(f"Default group & emblem: {default_group.title} ({default_group.pk})"))

            # 5. Public emblems
            # emblems_created = seed_public_emblems() or 0
            # self.stdout.write(self.style.SUCCESS(f"Created {emblems_created} public emblems"))

            # 6. Membership
            ensure_user_membership(default_group, su, role="admin", is_active=True)
            self.stdout.write(self.style.SUCCESS("Superuser added to Default Group as admin."))

        self.stdout.write(self.style.SUCCESS("Bootstrap complete."))
