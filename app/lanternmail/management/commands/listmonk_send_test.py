from django.core.management.base import BaseCommand
from lanternmail.services.listmonk_client import get_listmonk_client


class Command(BaseCommand):
    help = "Create a draft campaign and send a test email to specific addresses"

    def add_arguments(self, parser):
        parser.add_argument("--list-id", action="append", type=int, required=True)
        parser.add_argument("--to", action="append", required=True, help="Subscriber email (repeatable)")
        parser.add_argument("--name", default="Django smoke test")
        parser.add_argument("--subject", default="Lanternmail smoke test")
        parser.add_argument("--body", default="<p>If you got this, Django → Listmonk is working.</p>")

    def handle(self, *args, **opts):
        lm = get_listmonk_client()

        camp = lm.create_campaign(
            name=opts["name"],
            subject=opts["subject"],
            list_ids=opts["list_id"],
            body=opts["body"],
            tags=["django", "smoketest"],
        )

        self.stdout.write(f"create_campaign response: {camp}")

        campaign_id = camp.get("data", {}).get("id")
        if not campaign_id:
            raise RuntimeError(f"Campaign not created. Response: {camp}")


        # resp = lm.test_campaign(campaign_id=campaign_id, emails=opts["to"])
        resp = lm.test_campaign(campaign_id=campaign_id, subscribers=opts["to"])



        # camp = lm.create_campaign(
        #     name=opts["name"],
        #     subject=opts["subject"],
        #     list_ids=opts["list_id"],
        #     body=opts["body"],
        #     tags=["django", "smoketest"],
        # )
        # campaign_id = camp["data"]["id"]
        # resp = lm.test_campaign(campaign_id=campaign_id, subscribers=opts["to"])
        self.stdout.write(self.style.SUCCESS(f"campaign_id={campaign_id} resp={resp}"))
