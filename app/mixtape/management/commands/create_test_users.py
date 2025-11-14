# mixtape/management/commands/create_test_users.py
"""
Create test users for Playwright E2E testing

This command creates predictable test users that Playwright tests can use.
Run this before running E2E tests locally.

Usage:
    python manage.py create_test_users
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from profiles.services.profiles import ensure_user_profile

User = get_user_model()


class Command(BaseCommand):
    help = "Create test users for Playwright E2E testing"

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Creating test users for E2E testing..."))

        with transaction.atomic():
            # Test admin user (for most tests)
            admin_user, created = User.objects.get_or_create(
                username='admin',
                email='admin@mixtape.com',
                defaults={
                    'first_name': 'Admin',
                    'last_name': 'User',
                    'is_staff': True,
                    'is_superuser': True,
                }
            )
            if created or not admin_user.check_password('testpassword123'):
                admin_user.set_password('testpassword123')
                admin_user.save()
                self.stdout.write(self.style.SUCCESS(f"✓ Created/updated: {admin_user.username}"))
            else:
                self.stdout.write(f"  Already exists: {admin_user.username}")

            # Create profile
            ensure_user_profile(admin_user)

            # Existing site member (for @username invite tests)
            existing_user, created = User.objects.get_or_create(
                username='existinguser',
                email='existinguser@mixtape.com',
                defaults={
                    'first_name': 'Existing',
                    'last_name': 'User',
                }
            )
            if created or not existing_user.check_password('userpassword123'):
                existing_user.set_password('userpassword123')
                existing_user.save()
                self.stdout.write(self.style.SUCCESS(f"✓ Created/updated: {existing_user.username}"))
            else:
                self.stdout.write(f"  Already exists: {existing_user.username}")

            # Create profile
            ensure_user_profile(existing_user)

            # Group member (already in test group)
            group_member, created = User.objects.get_or_create(
                username='groupmember',
                email='groupmember@mixtape.com',
                defaults={
                    'first_name': 'Group',
                    'last_name': 'Member',
                }
            )
            if created or not group_member.check_password('memberpassword123'):
                group_member.set_password('memberpassword123')
                group_member.save()
                self.stdout.write(self.style.SUCCESS(f"✓ Created/updated: {group_member.username}"))
            else:
                self.stdout.write(f"  Already exists: {group_member.username}")

            # Create profile
            ensure_user_profile(group_member)

        self.stdout.write(self.style.SUCCESS("\n✅ Test users ready for E2E testing!"))
        self.stdout.write("\nTest credentials:")
        self.stdout.write("  Admin:    admin@mixtape.com / testpassword123")
        self.stdout.write("  Existing: existinguser@mixtape.com / userpassword123")
        self.stdout.write("  Member:   groupmember@mixtape.com / memberpassword123")
