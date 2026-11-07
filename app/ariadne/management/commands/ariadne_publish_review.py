"""
Ariadne -- Cass to Crossroads result flow (build plan
puddlejump/decisions/ariadne/build-plan-cass-to-crossroads-result-flow.md
§5-6, §6 piece 3).

Run on Cass by a person to publish one accessioned (CURATED) Review to
Crossroads' own database -- the "by hand" in the design note's §5.1
decision. Automatic publish-on-accession is a later refinement, not
built here.

Credentials: mints with its own `ARIADNE_PUBLISH_JWT_SECRET`, never
`SERVICE_JWT_SECRET` -- superseding the plan's original §5 (CTO,
2026-11-07; `decisions/ariadne/build-plan-cass-to-crossroads-result-flow.md`
Headnote). `SERVICE_JWT_SECRET` verifies every internal service token, so
a copy of it on Cass would let anyone there mint a production token for
any service and scope; this flow's secret is scoped to exactly this one
call, held only by Cass and Crossroads. ST-9 folds it into the one
minting module later (`puddlejump/zz/build-plan-service-trust.md`).

Usage:
  python manage.py ariadne_publish_review --review <uuid>
  python manage.py ariadne_publish_review --inquiry <uuid>   # latest CURATED review for that inquiry
"""

from __future__ import annotations

import time

import jwt
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ariadne.export import build_review_export_package
from ariadne.models import Inquiry, InquiryReview


def _mint_ariadne_publish_token(subject: str = "cass-ariadne-export") -> str:
    secret = getattr(settings, "ARIADNE_PUBLISH_JWT_SECRET", None)
    if not secret:
        raise CommandError(
            "ARIADNE_PUBLISH_JWT_SECRET is not configured -- this flow signs with its own "
            "secret, never SERVICE_JWT_SECRET (fail closed, not a fallback)."
        )
    now = int(time.time())
    ttl = int(getattr(settings, "ARIADNE_PUBLISH_JWT_TTL_SECONDS", 300))
    claims = {
        "sub": subject,
        "scopes": ["ariadne:publish"],
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "iss": getattr(settings, "ARIADNE_PUBLISH_JWT_ISS", "cass-ariadne"),
        "aud": getattr(settings, "ARIADNE_PUBLISH_JWT_AUD", "crossroads-ariadne-import"),
    }
    return jwt.encode(claims, secret, algorithm=getattr(settings, "ARIADNE_PUBLISH_JWT_ALG", "HS256"))


class Command(BaseCommand):
    help = "Publish one accessioned Ariadne Review from Cass to Crossroads."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--review", help="Review id to publish.")
        group.add_argument("--inquiry", help="Inquiry id; publishes its latest CURATED review.")

    def handle(self, *args, **options):
        if options["review"]:
            review = InquiryReview.objects.filter(id=options["review"]).select_related(
                "inquiry", "run__corpus_snapshot",
            ).first()
            if review is None:
                raise CommandError(f"No review {options['review']}.")
        else:
            inquiry = Inquiry.objects.filter(id=options["inquiry"]).first()
            if inquiry is None:
                raise CommandError(f"No inquiry {options['inquiry']}.")
            review = (
                InquiryReview.objects.filter(inquiry=inquiry, status=InquiryReview.Status.CURATED)
                .select_related("inquiry", "run__corpus_snapshot")
                .order_by("-version")
                .first()
            )
            if review is None:
                raise CommandError(f"Inquiry {inquiry.id} has no CURATED review to publish.")

        if review.status != InquiryReview.Status.CURATED:
            raise CommandError(
                f"Review {review.id} is {review.status!r}, not CURATED -- accession it first "
                "(design note §5.3's 'finished' signal)."
            )

        package = build_review_export_package(review)
        base_url = getattr(settings, "CROSSROADS_BASE_URL", None)
        if not base_url:
            raise CommandError("CROSSROADS_BASE_URL is not configured.")

        token = _mint_ariadne_publish_token()
        url = f"{base_url.rstrip('/')}/api/ariadne/inquiry-reviews/import/"

        self.stdout.write(f"Publishing review {review.id} (v{review.version}) to {url} ...")
        response = requests.post(
            url,
            json={"package": package},
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )

        if response.status_code >= 400:
            raise CommandError(f"Import failed ({response.status_code}): {response.text}")

        self.stdout.write(self.style.SUCCESS(
            f"Published review {review.id} (v{review.version}) to Crossroads: {response.json()}"
        ))
