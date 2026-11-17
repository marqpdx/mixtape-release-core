"""Create or delete the field-encryption key canary. Run by the CTO, once per
server; never part of a migration.

    manage.py field_encryption_canary            # read-only: print its state
    manage.py field_encryption_canary --create   # write the one canary row
    manage.py field_encryption_canary --delete   # undo: delete it

``--create`` writes one ExternalConnection row (no group, no owner, status
revoked) through EncryptedTextField, then re-reads it and checks it opens; if
it doesn't, the write is rolled back. It writes nothing when a canary already
opens, and refuses when one exists that doesn't (that row is the evidence:
find out why before deleting it). The row and why no member sees it:
``sourcework.encryption_canary``. Prints states and the row's id, never a
stored value or the key.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from fundamentals.management.commands.check_field_encryption import load_fernet
from sourcework.encryption_canary import (
    ABSENT,
    CANARY_ACCOUNT_ID,
    CANARY_DISPLAY_NAME,
    CANARY_PLAINTEXT,
    CANARY_PROVIDER,
    OPENS,
    canary_queryset,
    canary_state,
)


class Command(BaseCommand):
    help = "Create (--create) or delete (--delete) the field-encryption key canary row."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--create", action="store_true", help="Write the canary row.")
        group.add_argument("--delete", action="store_true", help="Delete the canary row (the undo).")

    def handle(self, *args, **options):
        if options["delete"]:
            return self._delete()

        fernet, reason = load_fernet()
        if fernet is None:
            raise CommandError(f"FIELD_ENCRYPTION_KEY is {reason}; nothing written.", returncode=1)

        before = canary_state(fernet)
        if not options["create"]:
            self.stdout.write(f"canary: {before.describe()}")
            return
        if before.state == OPENS:
            self.stdout.write(f"canary: {before.describe()}; nothing written.")
            return
        if before.state != ABSENT:
            raise CommandError(
                f"canary: {before.describe()}. Refusing to write a second one; "
                "find out why it fails, then --delete it if that is the decision.",
                returncode=1,
            )
        self._create(fernet)

    def _create(self, fernet):
        from sourcework.models import ExternalConnection, ExternalConnectionStatus

        with transaction.atomic():
            row = ExternalConnection.objects.create(
                group=None,
                owner=None,
                provider=CANARY_PROVIDER,
                provider_account_id=CANARY_ACCOUNT_ID,
                display_name=CANARY_DISPLAY_NAME,
                credential_reference="canary:not-a-credential",
                credential_payload=CANARY_PLAINTEXT,
                provider_scopes=[],
                status=ExternalConnectionStatus.REVOKED,
                revoked_at=timezone.now(),
                metadata={
                    "purpose": "field_encryption_canary",
                    "member_visible": False,
                    "undo": "manage.py field_encryption_canary --delete",
                },
            )
            after = canary_state(fernet)
            if after.state != OPENS or after.rows != 1:
                # Raising inside atomic() rolls the write back.
                raise CommandError(
                    f"canary written but reads back as: {after.describe()}; rolled back.",
                    returncode=1,
                )
        self.stdout.write(f"canary: created 1 row (id {row.pk}); {after.describe()}.")
        self.stdout.write("undo: manage.py field_encryption_canary --delete")

    def _delete(self):
        rows = canary_queryset()
        count = rows.count()
        rows.delete()
        self.stdout.write(f"canary: deleted {count} row(s).")
