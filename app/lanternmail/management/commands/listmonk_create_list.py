from django.core.management.base import BaseCommand
from lanternmail.services.listmonk_client import get_listmonk_client


class Command(BaseCommand):
    help = "Create a list in listmonk"

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--type", default="private", choices=["private", "public"])
        parser.add_argument("--optin", default="double", choices=["single", "double"])
        parser.add_argument("--description", default="")
        parser.add_argument("--tag", action="append", default=[])

    def handle(self, *args, **opts):
        lm = get_listmonk_client()
        resp = lm.create_list(
            name=opts["name"],
            list_type=opts["type"],
            optin=opts["optin"],
            tags=opts["tag"],
            description=opts["description"],
        )
        self.stdout.write(self.style.SUCCESS(str(resp)))
