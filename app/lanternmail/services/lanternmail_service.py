# lanternmail/services/lanternmail_service.py

# This keeps views thin and makes sponsorship logic easy later.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from groups.models import Group
from lanternmail.models import LanternmailList, LanternmailPost
from .exceptions import ListmonkBadRequestError, ListmonkUpstreamError
from .listmonk_client import ListmonkClient


@dataclass
class LanternmailService:
    lm: ListmonkClient

    def _safe_slug(self, display_name: str) -> str:
        return re.sub(r"[^a-zA-Z0-9\-]", "", display_name.lower().replace(" ", "-"))

    def create_group_list(
        self,
        *,
        group: Group,
        display_name: str,
        description: str,
        list_type: str,
        optin: str,
        tags: Optional[List[str]] = None,
    ) -> LanternmailList:
        # De-dup on Django side first.
        existing = LanternmailList.objects.filter(group=group, display_name=display_name).first()
        if existing:
            return existing

        # Namespaced listmonk name (unique across all groups).
        base = f"{group.slug}--{self._safe_slug(display_name)}"
        listmonk_name = base
        counter = 1
        while LanternmailList.objects.filter(listmonk_name=listmonk_name).exists():
            listmonk_name = f"{base}-{counter}"
            counter += 1

        lm_resp = self.lm.create_list(
            name=listmonk_name,
            list_type=list_type,
            optin=optin,
            tags=tags or ["lantern-mail", "group", group.slug],
            description=description or f"{display_name} - {group.title}",
        )
        lm_list = lm_resp["data"]

        # Write Django row atomically.
        try:
            with transaction.atomic():
                return LanternmailList.objects.create(
                    group=group,
                    listmonk_id=lm_list["id"],
                    listmonk_uuid=lm_list["uuid"],
                    display_name=display_name,
                    listmonk_name=lm_list["name"],
                    description=lm_list.get("description", description),
                )
        except IntegrityError as e:
            # If we race, return the existing one
            existing2 = LanternmailList.objects.filter(group=group, display_name=display_name).first()
            if existing2:
                return existing2
            raise

    def _post_campaign_name(self, post: LanternmailPost) -> str:
        return f"lanternmail:{post.group.slug}:{post.pk}"

    def _post_campaign_tags(self, post: LanternmailPost) -> list[str]:
        return [
            "lantern-mail",
            "lanternmail-post",
            f"group:{post.group.slug}",
            f"post:{post.pk}",
            f"audience:{post.audience_kind}",
        ]

    def create_or_update_post_campaign(
        self,
        *,
        post: LanternmailPost,
        body_html: str = "",
        content_type: str = "richtext",
    ) -> LanternmailPost:
        """
        Create or update the Listmonk draft campaign for a LanternmailPost.

        Listmonk is the delivery engine. The post remains the local source of
        truth, and only the upstream campaign id is mirrored onto the post.

        body_html: rendered HTML for the campaign body. When provided, body_text
        is sent as the plain-text altbody. When absent, body_text is used for
        both (sync/test flows where full HTML is not required).
        """
        if not post.mailing_list:
            raise ListmonkBadRequestError("LanternmailPost requires a mailing_list before campaign sync.")
        if post.status == LanternmailPost.STATUS_ARCHIVED:
            raise ListmonkBadRequestError("Archived LanternmailPosts cannot be synced to Listmonk.")
        if post.status == LanternmailPost.STATUS_SENT:
            raise ListmonkBadRequestError("Sent LanternmailPosts cannot be updated in Listmonk.")

        list_ids = [post.mailing_list.listmonk_id]
        tags = self._post_campaign_tags(post)
        name = self._post_campaign_name(post)
        campaign_body = body_html if body_html else post.body_text
        altbody = post.body_text if body_html else ""

        if post.listmonk_campaign_id:
            self.lm.update_campaign(
                campaign_id=post.listmonk_campaign_id,
                name=name,
                subject=post.subject,
                list_ids=list_ids,
                body=campaign_body,
                content_type=content_type,
                messenger="email",
                tags=tags,
                altbody=altbody,
            )
            return post

        response = self.lm.create_campaign(
            name=name,
            subject=post.subject,
            list_ids=list_ids,
            body=campaign_body,
            content_type=content_type,
            messenger="email",
            tags=tags,
            altbody=altbody,
        )
        campaign_id = response.get("data", {}).get("id")
        if not campaign_id:
            raise ListmonkUpstreamError("Listmonk create campaign response did not include data.id.")

        post.listmonk_campaign_id = campaign_id
        post.save(update_fields=["listmonk_campaign_id", "updated_at"])
        return post

    def send_post(self, *, post: LanternmailPost) -> LanternmailPost:
        """
        Dispatch a ready LanternmailPost through Listmonk.

        Renders HTML from body_json at send time — body_html is never stored.
        This is the only path that marks a post sent; PATCH cannot set status=sent.
        """
        if post.status != LanternmailPost.STATUS_READY:
            raise ListmonkBadRequestError("Only ready LanternmailPosts can be sent.")

        from utils.writing.writing_utils import render_html_from_prosemirror
        body_html = render_html_from_prosemirror(post.body_json)

        post = self.create_or_update_post_campaign(post=post, body_html=body_html)
        self.lm.update_campaign_status(post.listmonk_campaign_id, "running")

        post.status = LanternmailPost.STATUS_SENT
        post.sent_at = timezone.now()
        post.ingest_status = LanternmailPost.INGEST_ELIGIBLE
        post.save(update_fields=["status", "sent_at", "ingest_status", "updated_at"])
        return post
