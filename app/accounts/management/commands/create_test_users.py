# accounts/management/commands/create_test_users.py
"""
Create/update test users for Playwright E2E testing

This command ensures test users exist with known credentials.
Safe to run multiple times (idempotent).

Usage:
    python manage.py create_test_users
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from profiles.services.profiles import ensure_user_profile


User = get_user_model()


class Command(BaseCommand):
    help = "Create/update test users for Playwright E2E testing"

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Setting up test users for E2E testing..."))

        with transaction.atomic():
            # Test admin user (for most tests)
            admin_user = self._ensure_user(
                username="admin",
                email="admin@mixtape.com",
                password="testpassword123",
                first_name="Admin",
                last_name="User",
                is_staff=True,
                is_superuser=True,
            )

            # Existing site member (for @username invite tests)
            existing_user = self._ensure_user(
                username="existinguser",
                email="existinguser@mixtape.com",
                password="userpassword123",
                first_name="Existing",
                last_name="User",
            )

            # Group member (already in test group)
            group_member = self._ensure_user(
                username="groupmember",
                email="groupmember@mixtape.com",
                password="memberpassword123",
                first_name="Group",
                last_name="Member",
            )

        self.stdout.write(self.style.SUCCESS("\n✅ Test users ready for E2E testing!"))
        self.stdout.write("\nTest credentials:")
        self.stdout.write("  Admin:    admin@mixtape.com / testpassword123")
        self.stdout.write("  Existing: existinguser@mixtape.com / userpassword123")
        self.stdout.write("  Member:   groupmember@mixtape.com / memberpassword123")

    def _ensure_user(self, username, email, password, first_name, last_name, is_staff=False, is_superuser=False):
        """
        Get or create a user with the given credentials.
        Updates password if user exists to ensure it's correct.
        """
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "is_staff": is_staff,
                "is_superuser": is_superuser,
            }
        )

        # Update email if changed
        if user.email != email:
            user.email = email
            user.save()

        # Always set/update password to ensure it's correct
        if created or not user.check_password(password):
            user.set_password(password)
            user.save()
            action = "Created" if created else "Updated password for"
            self.stdout.write(self.style.SUCCESS(f"✓ {action}: {username}"))
        else:
            self.stdout.write(f"  Already exists: {username}")

        # Ensure profile exists
        ensure_user_profile(user)

        return user
