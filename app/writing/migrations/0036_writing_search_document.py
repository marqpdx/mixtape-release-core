import uuid

import django.contrib.postgres.indexes
import django.contrib.postgres.search
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("writing", "0035_workingdocument_cursor_position_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="WritingSearchDocument",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("variant", models.CharField(choices=[("published", "Published"), ("draft", "Draft")], max_length=12)),
                ("title", models.CharField(blank=True, max_length=255)),
                ("excerpt", models.TextField(blank=True)),
                ("body_text", models.TextField(blank=True)),
                ("search_vector", django.contrib.postgres.search.SearchVectorField(editable=False, null=True)),
                ("source_updated_at", models.DateTimeField()),
                ("source_hash", models.CharField(max_length=64)),
                ("piece", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="search_documents", to="writing.writingpiece")),
                ("working_document", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="search_document", to="writing.workingdocument")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    django.contrib.postgres.indexes.GinIndex(fields=["search_vector"], name="write_search_vector_gin"),
                    models.Index(fields=["variant", "source_updated_at"], name="write_search_variant_updated"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=(Q(variant="published", working_document__isnull=True) | Q(variant="draft", working_document__isnull=False)),
                        name="write_search_variant_wc_valid",
                    ),
                    models.UniqueConstraint(fields=["piece"], condition=Q(variant="published"), name="uniq_write_search_published"),
                ],
            },
        ),
    ]
