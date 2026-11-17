"""The field-encryption key canary: one labelled, non-member ExternalConnection
row whose credential_payload holds a known, non-secret value written through
EncryptedTextField. A restore or a deploy proves FIELD_ENCRYPTION_KEY by
showing that the stored token opens to that value.

Why this row is invisible to members: every member path reads ExternalConnection
through a group or an owner (sourcework.api.views, opportunities.services), and
this row has neither; its status is REVOKED, so switchboard.source_grants'
readiness check refuses it; it has no SourceGrant; and the admin already
excludes credential_payload. It is created and deleted only by the
``field_encryption_canary`` command, which the CTO runs on each server.

Nothing here prints or returns the stored value; callers get a state name.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import TextField
from django.db.models.functions import Cast

from fundamentals.encrypted_fields import looks_like_fernet_token

CANARY_PROVIDER = "mixtape_key_canary"
CANARY_ACCOUNT_ID = "field-encryption-canary"
CANARY_DISPLAY_NAME = "Field-encryption key canary (no member; safe to delete)"
# Known and deliberately not secret: the point is that anyone holding the key
# can check it opens to exactly this.
CANARY_PLAINTEXT = "mixtape field-encryption canary v1 (not a secret)"

ABSENT = "absent"
OPENS = "present and opens"
FAILS_DECRYPT = "FAILS: does not decrypt with this key"
FAILS_VALUE = "FAILS: decrypts, but not to the canary value"
FAILS_PLAINTEXT = "FAILS: stored value is not encrypted"


@dataclass(frozen=True)
class CanaryState:
    rows: int
    state: str

    @property
    def ok(self) -> bool:
        return self.state in (ABSENT, OPENS)

    def describe(self) -> str:
        if self.rows > 1:
            return f"{self.state} ({self.rows} rows)"
        return self.state


def canary_queryset():
    from sourcework.models import ExternalConnection

    return ExternalConnection._base_manager.filter(
        group__isnull=True,
        owner__isnull=True,
        provider=CANARY_PROVIDER,
        provider_account_id=CANARY_ACCOUNT_ID,
    )


def canary_state(fernet) -> CanaryState:
    """Decrypt the canary's raw stored value in memory and name its state.

    The Cast reads the column as plain text, so EncryptedTextField's own
    from_db_value (which raises on a bad token) never runs here.
    """
    from cryptography.fernet import InvalidToken

    raws = list(
        canary_queryset()
        .annotate(raw_value=Cast("credential_payload", output_field=TextField()))
        .values_list("raw_value", flat=True)
    )
    if not raws:
        return CanaryState(rows=0, state=ABSENT)
    worst = OPENS
    for raw in raws:
        if not raw or not looks_like_fernet_token(raw):
            worst = FAILS_PLAINTEXT
            continue
        try:
            opened = fernet.decrypt(raw.encode()).decode()
        except InvalidToken:
            worst = FAILS_DECRYPT
            continue
        if opened != CANARY_PLAINTEXT and worst == OPENS:
            worst = FAILS_VALUE
    return CanaryState(rows=len(raws), state=worst)
