import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("business", "0001_initial"),
        ("groups", "0016_groupcontext"),
        ("prospects", "0005_ec_phase1_prospects"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Client",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("primary_contact_name", models.CharField(blank=True, max_length=200)),
                ("primary_contact_email", models.EmailField(blank=True, max_length=254)),
                ("primary_contact_phone", models.CharField(blank=True, max_length=50)),
                ("website", models.URLField(blank=True)),
                ("business_type", models.CharField(blank=True, max_length=200)),
                ("contract_notes", models.TextField(blank=True)),
                ("billing_notes", models.TextField(blank=True)),
                ("group", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="client",
                    to="groups.group",
                )),
                ("prospect", models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="client",
                    to="prospects.businessprospect",
                )),
                ("created_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="created_clients",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
