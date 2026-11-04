# AtriumSession is now Dialogue (CTO, 2026-11-04; ST-3 Part B).
# Renames tables and fields, drops the long-lived process id, and adds what a
# Dialogue turn on the runtime worker needs: who spoke, a reply's status and
# failure code, its ActionRun, and each provider's catch-up point.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("atrium", "0009_initiative_log_help_text"),
        ("initiatives", "0029_rename_aperturelog_initiativelog"),
    ]

    operations = [
        migrations.RemoveConstraint("cloudagentsession", "unique_active_cloud_agent_session_per_provider"),
        migrations.RenameModel("AtriumSession", "Dialogue"),
        migrations.RenameModel("AtriumSessionEntry", "DialogueEntry"),
        migrations.RenameField("dialogueentry", "session", "dialogue"),
        migrations.RenameField("cloudagentsession", "atrium_session", "dialogue"),
        migrations.RenameField("distillate", "session", "dialogue"),
        migrations.RenameField("initiativedocument", "session", "dialogue"),
        migrations.RenameField("initiativedocument", "session_entry", "dialogue_entry"),
        migrations.RemoveField("dialogue", "pty_pid"),
        migrations.AddConstraint(
            "cloudagentsession",
            models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("dialogue", "provider"),
                name="unique_active_cloud_agent_session_per_provider",
            ),
        ),
        migrations.AddField(
            "dialogueentry", "speaker",
            models.CharField(blank=True, default="", help_text="For replies: the provider that answered (e.g. anthropic-claude-code, openai-codex). Blank for the person.", max_length=64),
        ),
        migrations.AddField(
            "dialogueentry", "status",
            models.CharField(choices=[("pending", "Pending"), ("streaming", "Streaming"), ("done", "Done"), ("failed", "Failed")], db_index=True, default="done", max_length=16),
        ),
        migrations.AddField(
            "dialogueentry", "error_code",
            models.CharField(blank=True, default="", help_text="Why a reply failed: runtime_missing, runtime_not_ready, mode_not_allowed, or failed.", max_length=64),
        ),
        migrations.AddField(
            "dialogueentry", "action_run",
            models.ForeignKey(blank=True, help_text="The governed record of the cloud call that wrote this reply (ST-7).", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="dialogue_entries", to="initiatives.actionrun"),
        ),
        migrations.AddField(
            "cloudagentsession", "seen_through",
            models.DateTimeField(blank=True, help_text="created_at of the last DialogueEntry this provider has been shown.", null=True),
        ),
        migrations.AddField(
            "distillate", "status",
            models.CharField(choices=[("pending", "Pending"), ("done", "Done"), ("failed", "Failed")], default="done", max_length=16),
        ),
        migrations.AddField(
            "distillate", "error_code",
            models.CharField(blank=True, default="", max_length=64),
        ),
    ]
