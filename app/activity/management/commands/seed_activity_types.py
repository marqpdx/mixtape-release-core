from django.core.management.base import BaseCommand
from activity.models import ActivityType

CANONICAL = [
    dict(code="chat.mention", title="Chat Mention",
         default_channel="messages", default_priority="critical",
         suppressible_by_user=False),
    dict(code="chat.participant.added", title="Added to Conversation",
         default_channel="activity", default_priority="normal",
         suppressible_by_user=True),
    dict(code="chat.conversation.created", title="Conversation Created",
         default_channel="activity", default_priority="normal",
         suppressible_by_user=True),
    dict(code="chat.conversation.updated", title="Conversation Updated",
         default_channel="activity", default_priority="normal",
         suppressible_by_user=True),
    dict(code="chat.message.reaction", title="Reaction to Your Message",
        default_channel="activity", default_priority="low",
        suppressible_by_user=True),
]

class Command(BaseCommand):
    help = "Seed canonical ActivityType rows for chat"

    def handle(self, *args, **options):
        created = 0
        for row in CANONICAL:
            at, was_created = ActivityType.objects.get_or_create(
                code=row["code"],
                defaults=dict(
                    title=row["title"],
                    summary="",
                    default_channel=row["default_channel"],
                    default_priority=row["default_priority"],
                    suppressible_by_user=row["suppressible_by_user"],
                ),
            )
            created += int(was_created)
            self.stdout.write(self.style.SUCCESS(f"{'✔' if was_created else '•'} {at.code}"))
        self.stdout.write(self.style.SUCCESS(f"Done. Created {created} new ActivityType rows."))
