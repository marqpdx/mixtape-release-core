import uuid

from django.db import migrations


SEED_QUESTIONS = [
    {
        "order_index": 1,
        "prompt": "Tell us about your business.",
        "help_text": "What does it do? Who do you serve? What kind of work happens day to day?",
    },
    {
        "order_index": 2,
        "prompt": "Why do you do this work?",
        "help_text": "What got you into it? What excites you? What values or tenets matter most to you?",
    },
    {
        "order_index": 3,
        "prompt": "How does the business currently run?",
        "help_text": "Where does important information live? What documents, systems, or habits do you rely on? What lives mostly in someone's head?",
    },
    {
        "order_index": 4,
        "prompt": "Where do you feel friction or waste?",
        "help_text": "What frustrates you? Where do you repeat yourself? What feels harder than it should?",
    },
    {
        "order_index": 5,
        "prompt": "Where do you want to grow or improve?",
        "help_text": "What do you wish worked more smoothly? What would make the biggest difference in the next 6–12 months?",
    },
    {
        "order_index": 6,
        "prompt": "What would you want help with first?",
        "help_text": "If we could improve one area quickly, what should it be? What would feel most valuable right away?",
    },
]


def seed_questions(apps, schema_editor):
    ProspectQuestion = apps.get_model("prospects", "ProspectQuestion")
    for q in SEED_QUESTIONS:
        ProspectQuestion.objects.create(
            id=uuid.uuid4(),
            prompt=q["prompt"],
            help_text=q["help_text"],
            order_index=q["order_index"],
            is_active=True,
            question_kind="long_text",
        )


def unseed_questions(apps, schema_editor):
    ProspectQuestion = apps.get_model("prospects", "ProspectQuestion")
    ProspectQuestion.objects.filter(
        prompt__in=[q["prompt"] for q in SEED_QUESTIONS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("prospects", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_questions, unseed_questions),
    ]
