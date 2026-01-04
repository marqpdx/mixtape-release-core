import json
from django.core.management.base import BaseCommand
from lanternmail.services.listmonk_client import get_listmonk_client


class Command(BaseCommand):
    help = "Create a subscriber in listmonk"

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", default="")
        parser.add_argument("--attribs", default="{}")
        parser.add_argument("--list-id", action="append", type=int, default=[])

    def handle(self, *args, **opts):
        lm = get_listmonk_client()
        attribs = json.loads(opts["attribs"])
        resp = lm.create_subscriber(
            email=opts["email"],
            name=opts["name"],
            attribs=attribs,
            lists=opts["list_id"] or None,
            preconfirm_subscriptions=True,
        )
        self.stdout.write(self.style.SUCCESS(str(resp)))
