from django.core.management.base import BaseCommand
from lanternmail.services.listmonk_client import get_listmonk_client


class Command(BaseCommand):
    help = "Add an existing subscriber to one or more lists"

    def add_arguments(self, parser):
        parser.add_argument("--subscriber-id", type=int, required=True)
        parser.add_argument("--list-id", action="append", type=int, required=True)

    def handle(self, *args, **opts):
        lm = get_listmonk_client()
        resp = lm.update_subscriber_lists(
            subscriber_id=opts["subscriber_id"],
            add=opts["list_id"],
            status="confirmed",
        )
        self.stdout.write(self.style.SUCCESS(str(resp)))
