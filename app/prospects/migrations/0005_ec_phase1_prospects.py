import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("prospects", "0004_alter_prospectresponse_unique_together_and_more"),
        ("groups", "0015_stackroom_library_id"),
    ]

    operations = [
        # EC-B1 — BusinessProspect.converted_to_group: IntegerField → FK to groups.Group
        migrations.RemoveField(
            model_name="businessprospect",
            name="converted_to_group_id",
        ),
        migrations.AddField(
            model_name="businessprospect",
            name="converted_to_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="prospect_source",
                to="groups.group",
            ),
        ),

        # EC-B2 — ProspectResponse.converted_at
        migrations.AddField(
            model_name="prospectresponse",
            name="converted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),

        # EC-B3 — ProspectQuestion.triggers_persona_creation
        migrations.AddField(
            model_name="prospectquestion",
            name="triggers_persona_creation",
            field=models.BooleanField(default=False),
        ),

        # EC-B4 — OnboardingQuestion
        migrations.CreateModel(
            name="OnboardingQuestion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("text", models.TextField()),
                ("category", models.CharField(
                    choices=[
                        ("identity", "Identity & Founding"),
                        ("presentation", "Outward Presentation"),
                        ("operations", "Operational Character"),
                        ("relationships", "Relationships"),
                        ("knowledge", "Knowledge & People"),
                    ],
                    max_length=32,
                )),
                ("order", models.PositiveIntegerField(default=0)),
                ("triggers_persona_creation", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["category", "order"],
            },
        ),

        # EC-B5 — ProspectQuestionOnboardingMap
        migrations.CreateModel(
            name="ProspectQuestionOnboardingMap",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("onboarding_question", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="prospect_maps",
                    to="prospects.onboardingquestion",
                )),
                ("prospect_question", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="onboarding_map",
                    to="prospects.prospectquestion",
                )),
            ],
            options={
                "verbose_name": "Prospect → Onboarding Question Map",
            },
        ),
    ]
