# Generated manually for Sourcework V1.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("groups", "0035_group_tagline"),
        ("initiatives", "0023_aperturelog_source_timestamp"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalConnection",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(db_index=True, default="google_gmail", max_length=64)),
                ("provider_account_id", models.CharField(blank=True, default="", max_length=255)),
                ("display_name", models.CharField(blank=True, default="", max_length=255)),
                ("credential_reference", models.CharField(blank=True, default="", max_length=255)),
                ("provider_scopes", models.JSONField(blank=True, default=list)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("ready", "Ready"), ("revoked", "Revoked"), ("failed", "Failed")], db_index=True, default="draft", max_length=24)),
                ("connected_at", models.DateTimeField(blank=True, null=True)),
                ("refreshed_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sourcework_connections", to="groups.group")),
                ("owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="SourceGrant",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("resource_kind", models.CharField(default="gmail_label", max_length=64)),
                ("resource_id", models.CharField(max_length=255)),
                ("display_name", models.CharField(max_length=255)),
                ("capabilities", models.JSONField(blank=True, default=list)),
                ("status", models.CharField(choices=[("active", "Active"), ("revoked", "Revoked")], db_index=True, default="active", max_length=24)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("connection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="source_grants", to="sourcework.externalconnection")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("initiative", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="source_grants", to="initiatives.initiative")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ProvisionalThing",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("possible_type", models.CharField(blank=True, default="", max_length=80)),
                ("status", models.CharField(choices=[("provisional", "Provisional"), ("ready", "Ready"), ("excluded", "Excluded"), ("merged", "Merged"), ("promoted", "Promoted"), ("archived", "Archived")], db_index=True, default="provisional", max_length=24)),
                ("preferred_name", models.CharField(blank=True, default="", max_length=255)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("organization_guess", models.CharField(blank=True, default="", max_length=255)),
                ("relationship_context", models.TextField(blank=True, default="")),
                ("name_source", models.CharField(choices=[("header", "Header"), ("signature", "Signature"), ("human_verified", "Human verified"), ("unknown", "Unknown")], default="unknown", max_length=32)),
                ("name_confidence", models.CharField(choices=[("high", "High"), ("medium", "Medium"), ("low", "Low")], default="low", max_length=16)),
                ("name_status", models.CharField(choices=[("ready", "Ready"), ("review_suggested", "Review suggested"), ("needs_review", "Needs review")], default="needs_review", max_length=32)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="provisional_things", to="groups.group")),
                ("verified_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="verified_provisional_things", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["preferred_name", "email"],
            },
        ),
        migrations.CreateModel(
            name="SourceEvidence",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(default="google_gmail", max_length=64)),
                ("provider_message_id", models.CharField(max_length=255)),
                ("provider_thread_id", models.CharField(blank=True, default="", max_length=255)),
                ("label_id", models.CharField(blank=True, default="", max_length=255)),
                ("sender_email", models.EmailField(blank=True, default="", max_length=254)),
                ("sender_display_name_raw", models.CharField(blank=True, default="", max_length=255)),
                ("sender_header_raw", models.TextField(blank=True, default="")),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("subject", models.TextField(blank=True, default="")),
                ("source_fingerprint", models.CharField(db_index=True, max_length=128)),
                ("body_snapshot_status", models.CharField(default="not_stored", max_length=64)),
                ("bounded_excerpt", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("ingested_at", models.DateTimeField(auto_now_add=True)),
                ("source_grant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evidence", to="sourcework.sourcegrant")),
            ],
            options={
                "ordering": ["-sent_at", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="WorkingSet",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=255)),
                ("purpose", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("active", "Active"), ("closed", "Closed"), ("archived", "Archived")], db_index=True, default="active", max_length=24)),
                ("summary", models.JSONField(blank=True, default=dict)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sourcework_working_sets", to="groups.group")),
                ("initiative", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="working_sets", to="initiatives.initiative")),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="WorkingSetMembership",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(db_index=True, default="active", max_length=24)),
                ("position", models.PositiveIntegerField(default=0)),
                ("note", models.TextField(blank=True, default="")),
                ("provisional_thing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="working_set_memberships", to="sourcework.provisionalthing")),
                ("working_set", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="sourcework.workingset")),
            ],
            options={
                "ordering": ["position", "created_at"],
            },
        ),
        migrations.AddField(
            model_name="provisionalthing",
            name="evidence",
            field=models.ManyToManyField(blank=True, related_name="provisional_things", to="sourcework.sourceevidence"),
        ),
        migrations.AddIndex(
            model_name="externalconnection",
            index=models.Index(fields=["group", "provider", "status"], name="sourcework__group_i_e52eec_idx"),
        ),
        migrations.AddIndex(
            model_name="sourcegrant",
            index=models.Index(fields=["connection", "resource_kind", "resource_id"], name="sourcework__connect_6765a0_idx"),
        ),
        migrations.AddIndex(
            model_name="sourcegrant",
            index=models.Index(fields=["initiative", "status"], name="sourcework__initiat_33f7d5_idx"),
        ),
        migrations.AddConstraint(
            model_name="sourcegrant",
            constraint=models.UniqueConstraint(fields=("connection", "resource_kind", "resource_id", "initiative"), name="sourcework_unique_grant_per_initiative"),
        ),
        migrations.AddIndex(
            model_name="provisionalthing",
            index=models.Index(fields=["group", "possible_type", "status"], name="sourcework__group_i_115d8e_idx"),
        ),
        migrations.AddIndex(
            model_name="provisionalthing",
            index=models.Index(fields=["group", "email"], name="sourcework__group_i_3f058e_idx"),
        ),
        migrations.AddIndex(
            model_name="provisionalthing",
            index=models.Index(fields=["name_status", "name_confidence"], name="sourcework__name_st_22207f_idx"),
        ),
        migrations.AddIndex(
            model_name="sourceevidence",
            index=models.Index(fields=["source_grant", "source_fingerprint"], name="sourcework__source__174034_idx"),
        ),
        migrations.AddIndex(
            model_name="sourceevidence",
            index=models.Index(fields=["sender_email"], name="sourcework__sender__2c08e1_idx"),
        ),
        migrations.AddConstraint(
            model_name="sourceevidence",
            constraint=models.UniqueConstraint(fields=("source_grant", "provider_message_id"), name="sourcework_unique_message_per_grant"),
        ),
        migrations.AddIndex(
            model_name="workingset",
            index=models.Index(fields=["group", "status"], name="sourcework__group_i_79f05d_idx"),
        ),
        migrations.AddIndex(
            model_name="workingset",
            index=models.Index(fields=["initiative", "status"], name="sourcework__initiat_55d218_idx"),
        ),
        migrations.AddConstraint(
            model_name="workingsetmembership",
            constraint=models.UniqueConstraint(fields=("working_set", "provisional_thing"), name="sourcework_unique_thing_per_working_set"),
        ),
    ]
