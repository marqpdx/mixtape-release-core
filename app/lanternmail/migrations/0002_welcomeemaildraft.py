import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lanternmail", "0001_initial"),
        ("groups", "0016_groupcontext"),
        ("prospects", "0005_ec_phase1_prospects"),
    ]

    operations = [
        migrations.CreateModel(
            name="WelcomeEmailDraft",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("prospect", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="welcome_drafts",
                    to="prospects.businessprospect",
                )),
                ("group", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="welcome_drafts",
                    to="groups.group",
                )),
                ("to_name", models.CharField(max_length=200)),
                ("to_email", models.EmailField()),
                ("subject", models.CharField(max_length=300)),
                ("body", models.TextField()),
                ("status", models.CharField(
                    choices=[("draft", "Draft"), ("sent", "Sent")],
                    default="draft",
                    max_length=10,
                )),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Welcome Email Draft",
                "ordering": ["-created_at"],
                "abstract": False,
            },
        ),
    ]
