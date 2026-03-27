import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0009_admission_policy_to_group"),
        ("writing", "0012_add_writing_synopsis"),
    ]

    operations = [
        migrations.CreateModel(
            name="WritingSeries",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=255, help_text="Section header, e.g. 'Welcome'")),
                ("slug", models.SlugField(max_length=255)),
                ("phase_num", models.PositiveSmallIntegerField(
                    blank=True,
                    null=True,
                    help_text="Sort order and lookup key; matches `phase:` frontmatter field",
                )),
                ("subtitle", models.TextField(blank=True, null=True, help_text="Optional tagline from calendar description")),
                ("group", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="writing_series",
                    to="groups.group",
                )),
            ],
            options={
                "verbose_name": "Writing Series",
                "verbose_name_plural": "Writing Series",
                "ordering": ["phase_num", "title"],
                "unique_together": {("group", "slug")},
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="writingpiece",
            name="series",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="pieces",
                to="writing.writingseries",
            ),
        ),
        migrations.AddField(
            model_name="writingpiece",
            name="series_order",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text="Position within the series; lower = earlier",
            ),
        ),
    ]
