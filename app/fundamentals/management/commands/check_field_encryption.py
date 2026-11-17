"""Read-only probe: does FIELD_ENCRYPTION_KEY open what is stored?

Prints counts and state names only, never a stored value or the key:

    key: well formed
    chat_chatmessage.text: fernet-shaped ok 0, failed 0
    sourcework_externalconnection.credential_payload: fernet-shaped ok 1, failed 0
    canary: present and opens
    result: OK

Every EncryptedTextField column is checked (found from the models, so a new
one is covered without editing this file). Values are read as plain text and
decrypted in memory; nothing is written. The canary row, when present, is
counted in its table as well as on its own line.

Exits non-zero on a missing or malformed key, any ``failed`` above 0, or a
canary that is present but does not open. An absent canary is not a failure
unless ``--require-canary`` is given (use it once the canary exists on that
server, and in a restore drill).

Replaces the pasted probe in Puddlejump's scrub-and-deploy batch, section 4.1.
"""

from __future__ import annotations

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import TextField
from django.db.models.functions import Cast

from fundamentals.encrypted_fields import EncryptedTextField, looks_like_fernet_token

_FERNET_PREFIX = "gAAAAA"
_CHUNK = 500


def load_fernet():
    """Return (fernet, None), or (None, reason). The reason names no value."""
    from cryptography.fernet import Fernet

    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        return None, "missing"
    try:
        return Fernet(key.encode() if isinstance(key, str) else key), None
    except Exception as exc:  # ValueError / binascii.Error on a malformed key
        return None, f"malformed ({type(exc).__name__})"


def encrypted_columns():
    """Yield (model, field) for every concrete EncryptedTextField."""
    for model in apps.get_models():
        for field in model._meta.concrete_fields:
            if isinstance(field, EncryptedTextField):
                yield model, field


def count_column(model, field, fernet) -> tuple[int, int]:
    from cryptography.fernet import InvalidToken

    ok = failed = 0
    raws = (
        model._base_manager.annotate(raw_value=Cast(field.name, output_field=TextField()))
        .filter(raw_value__startswith=_FERNET_PREFIX)
        .order_by()
        .values_list("raw_value", flat=True)
        .iterator(chunk_size=_CHUNK)
    )
    for raw in raws:
        if not looks_like_fernet_token(raw):
            continue
        try:
            fernet.decrypt(raw.encode())
        except InvalidToken:
            failed += 1
        else:
            ok += 1
    return ok, failed


class Command(BaseCommand):
    help = (
        "Read-only: check FIELD_ENCRYPTION_KEY opens every stored Fernet value "
        "and the key canary. Prints counts only; writes nothing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--require-canary",
            action="store_true",
            help="Treat an absent canary as a failure.",
        )

    def handle(self, *args, **options):
        from sourcework.encryption_canary import ABSENT, canary_state

        fernet, reason = load_fernet()
        if fernet is None:
            self.stdout.write(f"key: {reason}")
            self.stdout.write("result: FAILED")
            raise CommandError(f"FIELD_ENCRYPTION_KEY is {reason}.", returncode=1)
        self.stdout.write("key: well formed")

        problems = []
        for model, field in sorted(
            encrypted_columns(), key=lambda mf: (mf[0]._meta.db_table, mf[1].column)
        ):
            ok, failed = count_column(model, field, fernet)
            name = f"{model._meta.db_table}.{field.column}"
            self.stdout.write(f"{name}: fernet-shaped ok {ok}, failed {failed}")
            if failed:
                problems.append(f"{name} has {failed} value(s) that do not decrypt")

        canary = canary_state(fernet)
        self.stdout.write(f"canary: {canary.describe()}")
        if not canary.ok:
            problems.append("the canary does not open")
        elif canary.state == ABSENT and options["require_canary"]:
            problems.append("the canary is absent (--require-canary)")

        if problems:
            self.stdout.write("result: FAILED")
            raise CommandError("; ".join(problems) + ".", returncode=1)
        self.stdout.write("result: OK")
