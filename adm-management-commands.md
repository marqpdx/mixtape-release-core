# Management Commands — mixtape-release-core

All commands run from `app/` with the virtual environment active:

```
python manage.py <command_name> [options]
```

Commands that accept `--dry-run` are safe to run in production for inspection.
Commands marked **[BACKFILL]** are one-off data repair tools; idempotent unless noted.
Commands marked **[SEED]** populate reference/fixture data; all are idempotent.

---

## Naming Conflicts (Action Required)

Two command names are registered in **two apps each**. Django resolves this silently by
using whichever app appears **last** in `INSTALLED_APPS`. The losing copy is dead code.

| Command | Apps | Active (last in INSTALLED_APPS) | Notes |
|---|---|---|---|
| `bootstrap_mixtape` | `accounts`, `mixtape` | `accounts` | `mixtape` app is **not** in INSTALLED_APPS — `mixtape/management/commands/bootstrap_mixtape.py` is unreachable dead code |
| `create_test_users` | `accounts`, `mixtape` | `accounts` | Same — `mixtape/management/commands/create_test_users.py` is unreachable dead code |

The two versions are nearly identical but differ in minor details. The `mixtape` package
versions should be removed or consolidated.

---

## accounts

### `bootstrap_mixtape`
Initialize the platform from scratch: superuser, emblem types, default group, public
emblems, and superuser membership.

- In `DEBUG` mode uses hardcoded dev credentials.
- In production prompts interactively for password.
- Idempotent — safe to re-run.

```
python manage.py bootstrap_mixtape
```

### `create_test_users`
Create or reset three predictable E2E test users (`admin`, `existinguser`,
`groupmember`) with known passwords. Always resets passwords on re-run.

```
python manage.py create_test_users
```

Credentials printed on completion. Use only in dev/test environments.

### `setup_puddlejump_oauth`
Create (or update redirect URIs on) the OAuth2 Application record for the Puddlejump
desktop sync client. Uses `client_id=puddlejump-desktop`, public client, PKCE.

```
python manage.py setup_puddlejump_oauth
```

---

## activity

### `seed_activity_types` [SEED]
Seed canonical `ActivityType` rows for chat events (`chat.mention`,
`chat.participant.added`, etc.). Idempotent via `get_or_create` on `code`.

```
python manage.py seed_activity_types
```

---

## contexts

### `seed_context_definitions` [SEED]
Seed `ContextDefinition` vocabulary records. Defaults to three built-in definitions
(`course-default-chat`, `group-default-chat`, `cohort-chat`). Accepts a JSON file
override and optional `--prune` to delete entries not in the provided set.

```
python manage.py seed_context_definitions
python manage.py seed_context_definitions --from-file ./context_defs.json
python manage.py seed_context_definitions --from-file ./context_defs.json --prune
python manage.py seed_context_definitions --dry-run
```

Options: `--from-file PATH`, `--prune`, `--dry-run`

---

## curation

### `backfill_core_resources` [BACKFILL]
Create a "Core Resources" `Collection` for every active group that doesn't already
have one. This is the backfill counterpart to the on-inception creation hook that
should fire when a new group is created.

```
python manage.py backfill_core_resources
python manage.py backfill_core_resources --dry-run
```

Options: `--dry-run`

> **Note:** A "Core Resources" collection should be created automatically when a group
> is first created. If that inception hook does not yet exist, this backfill command
> is the operational workaround. Track creation of the inception hook to make this
> truly redundant.

---

## distribution

### `seed_distribution_sources` [SEED]
Seed global distribution `Source` records (currently: `linkedin`). Optionally seed
a per-group `activity_stream` source for one or more groups.

```
python manage.py seed_distribution_sources
python manage.py seed_distribution_sources --group crossroads --group my-group
```

Options: `--group SLUG` (repeatable)

---

## feedback

### `seed_feedback_beacon` [SEED]
Create or update a `FeedbackBeacon` record by key. All fields are passed as CLI
options; useful for scripted beacon provisioning.

```
python manage.py seed_feedback_beacon \
  --key emblems_v1 \
  --title "Emblem Feedback" \
  --body "Share your thoughts." \
  --scope global
```

Options: `--key` (required), `--title` (required), `--body`, `--feature-context`,
`--scope` (`global|route|component`), `--route-pattern`, `--inactive`

---

## groups

### `add_user_to_group_with_role`
Add a user to a group with a given role, or grant an additional role if already a
member. Assigns the default permission profile on first join.

```
python manage.py add_user_to_group_with_role <username> <group-slug> <role>
```

Roles: `member`, `steward`, `admin`, `owner`

### `backfill_member_startup` [BACKFILL]
Run `MemberStartupService` for all active Crossroads members. Provisions Personal
Initiative and ApertureLog for members who joined before those features existed.

```
python manage.py backfill_member_startup
python manage.py backfill_member_startup --dry-run
```

Options: `--dry-run`

### `resend_invitation`
Resend a group invitation email by invitation ID, or by email + group slug. Looks up
the most recent `InviteLink`, regenerates the invite URL, and queues
`send_invitation_email` via Celery. Requires the invitation to be `PENDING` unless
`--force` is passed.

```
python manage.py resend_invitation --invitation-id 42
python manage.py resend_invitation --email alice@example.com --group my-group
python manage.py resend_invitation --email alice@example.com --group my-group --dry-run
python manage.py resend_invitation --invitation-id 42 --force
```

Options: `--invitation-id`, `--email`, `--group`, `--dry-run`, `--force`

> **Note:** `resend_invitation` and `resend_invite` do the same job with slightly
> different interfaces (one takes `--invitation-id`, the other takes a positional
> email). Consider consolidating into one command.

### `resend_invite`
Resend a pending invitation by email address. If the email has invitations in
multiple groups, requires `--group` to disambiguate.

```
python manage.py resend_invite alice@example.com
python manage.py resend_invite alice@example.com --group my-group
python manage.py resend_invite alice@example.com --group my-group --force
python manage.py resend_invite alice@example.com --group my-group --dry-run
```

Options: `--group SLUG`, `--force`, `--dry-run`

### `retire_wrc_group`
One-off maintenance command for the Wellness Resource Center group swap. Renames
two WRC-related groups, reassigns all sponsor-backed content from the deprecated
group to the surviving group, and deletes the deprecated group.

```
python manage.py retire_wrc_group
python manage.py retire_wrc_group --dry-run
```

Options: `--dry-run`

> This was a one-time operation and has been run. Retained here for audit trail.

---

## identity

### `fix_missing_emblem_renders`
Re-render `EmblemAvatar` records that are missing size URLs. Use `--force` to
re-render all emblems regardless.

```
python manage.py fix_missing_emblem_renders
python manage.py fix_missing_emblem_renders --dry-run
python manage.py fix_missing_emblem_renders --force
```

Options: `--dry-run`, `--force`

### `seed_emblem_avatar_types` [SEED]
Seed `EmblemAvatarType` records for all supported engines and styles (`upload`,
`initials/rounded`, `dicebear/identicon`, `dicebear/shapes`, `dicebear/lorelei`,
`dicebear/croodles`, `dicebear/big-ears`). Idempotent.

```
python manage.py seed_emblem_avatar_types
```

### `seed_person_emblems` [SEED]
Seed a set of person-style `EmblemAvatar` records (croodles, lorelei, big-ears)
with nature-name seeds. Pre-renders images by default.

```
python manage.py seed_person_emblems
python manage.py seed_person_emblems --lazy
```

Options: `--lazy` (skip pre-rendering; images render on first use)

### `seed_public_emblems` [SEED]
Seed the public emblem library: DiceBear identicons (15 nature seeds), shapes
(10 seeds), and initials (5 pairs). Pre-renders by default.

```
python manage.py seed_public_emblems
python manage.py seed_public_emblems --lazy
```

Options: `--lazy`

---

## inkwell

### `prune_startup_log`
Delete `StartupLog` records older than N days (default 30). Use for routine log
cleanup.

```
python manage.py prune_startup_log
python manage.py prune_startup_log --days 60
```

Options: `--days N` (default: 30)

### `reset_startup_locks`
Remove all startup lock files from `/tmp/cdoc_locks/`. Forces all startup tasks
to re-run on next startup.

```
python manage.py reset_startup_locks
```

### `run_startup`
Run the Inkwell AI startup tasks (LLM warm-up, RAG ingest, etc.). Use `--force`
to bypass the lock and re-run even if a lock file exists.

```
python manage.py run_startup
python manage.py run_startup --force
```

Options: `--force`

### `show_book_count`
Compare the number of ingested books between the Django DB (`IngestedFile`) and the
Qdrant vector store. Useful for diagnosing sync issues.

```
python manage.py show_book_count
python manage.py show_book_count --collection gutenberg25 --qdrant-url http://localhost:6333
```

Options: `--collection` (default: `gutenberg25`), `--qdrant-url` (default: `http://localhost:6333`)

### `show_startup_log`
Display recent `StartupLog` runs. Outputs human-readable or JSON format.

```
python manage.py show_startup_log
python manage.py show_startup_log --limit 10
python manage.py show_startup_log --json
```

Options: `--limit N` (default: 5), `--json`

### `trigger_task`
Manually trigger a Celery task that sends a request to FastAPI (task ID hardcoded
to 1). Development/diagnostic tool.

```
python manage.py trigger_task
```

### `watch_ingest`
Watch `ai/ebooks/to_ingest/` for new `.txt` URL list files, parse them via
`parse_gutenberg_url_file`, and move processed files to `ai/ebooks/processed/`.
Long-running process; terminate with Ctrl-C.

```
python manage.py watch_ingest
```

---

## lanternmail

### `listmonk_add_to_list`
Add an existing Listmonk subscriber to one or more lists (confirmed status).

```
python manage.py listmonk_add_to_list --subscriber-id 12 --list-id 3 --list-id 7
```

Options: `--subscriber-id` (required), `--list-id` (required, repeatable)

### `listmonk_create_list`
Create a mailing list in Listmonk.

```
python manage.py listmonk_create_list --name "Monthly Digest" --type private --optin double
```

Options: `--name` (required), `--type` (`private|public`, default: `private`),
`--optin` (`single|double`, default: `double`), `--description`, `--tag` (repeatable)

### `listmonk_create_subscriber`
Create a new subscriber in Listmonk, optionally adding them to lists immediately.

```
python manage.py listmonk_create_subscriber --email alice@example.com --name "Alice"
python manage.py listmonk_create_subscriber --email alice@example.com --list-id 3
```

Options: `--email` (required), `--name`, `--attribs JSON`, `--list-id` (repeatable)

### `listmonk_send_test`
Create a draft campaign in Listmonk and send a test email to specified subscribers.
Smoke-test for the Django → Listmonk connection.

```
python manage.py listmonk_send_test --list-id 3 --to alice@example.com
```

Options: `--list-id` (required, repeatable), `--to` (required, repeatable),
`--name`, `--subject`, `--body`

---

## mixtape (project package — commands NOT active)

> The `mixtape` package is **not listed in INSTALLED_APPS**, so these commands are
> never discovered by Django. They are dead code. Consider deleting or merging into
> the `accounts` or `mixtape` app equivalents.

- `bootstrap_mixtape` — duplicate of `accounts/management/commands/bootstrap_mixtape.py`
- `create_test_users` — near-duplicate of `accounts/management/commands/create_test_users.py`

---

## ops

### `ingest_build_log`
Parse all `*.md` files in a build-log-inbox directory and upsert them into the
`BuildLogEntry` model. Idempotent via `update_or_create` on `commit_hash`.

```
python manage.py ingest_build_log --inbox-dir ../puddlejump/build-log-inbox/
```

Options: `--inbox-dir PATH` (required)

---

## prospects

### `backfill_prospect_client` [BACKFILL]
Create `business.Client` records for `BusinessProspect` instances that were
converted to groups before the `Client` model existed.

```
python manage.py backfill_prospect_client
python manage.py backfill_prospect_client --dry-run
python manage.py backfill_prospect_client --prospect-slug acme-co
```

Options: `--dry-run`, `--prospect-slug SLUG`

### `seed_onboarding_questions` [SEED]
Seed `OnboardingQuestion` records from the canonical question bank (EC-B8).
Organized by category: `identity`, `presentation`, `operations`, `relationships`,
`knowledge`. Idempotent — skips questions that already exist by exact text match.

```
python manage.py seed_onboarding_questions
```

### `seed_prospect_onboarding_map` [SEED]
Seed `ProspectQuestionOnboardingMap` entries that link `ProspectQuestion` records
to their `OnboardingQuestion` equivalents (EC-B9). Requires EC-B8
(`seed_onboarding_questions`) to have run first.

```
python manage.py seed_prospect_onboarding_map
```

---

## writing

### `seed_writing_series` [SEED]
Seed `WritingSeries` records for the Article Calendar phases (Phase 0–8) attached
to a given group. Idempotent via `get_or_create` on `(group, slug)`.

```
python manage.py seed_writing_series --group crossroads
python manage.py seed_writing_series --group crossroads --dry-run
```

Options: `--group SLUG` (required), `--dry-run`

### `writing_import_docx`
Import a `.docx` file into a `WritingPiece` with TipTap JSON body. Resolves author
by UUID or email; resolves sponsor in `model_name:object_id` format. Creates an
`ImportReceipt` for idempotency. Optionally generates outline nodes from headings.

```
python manage.py writing_import_docx \
  --path /path/to/file.docx \
  --author alice@example.com \
  --sponsor group:abc-123 \
  --kind dispatch \
  --enable-outline \
  --dry-run
```

Options: `--path` (required), `--author` (required), `--sponsor` (required),
`--kind` (default: `dispatch`), `--title`, `--addressed-to` (`public|crossroads|self`),
`--enable-outline`, `--source-url`, `--force` (skip idempotency check), `--dry-run`
