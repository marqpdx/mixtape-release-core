# lanternmail/services/lanternmail_service.py

# This keeps views thin and makes sponsorship logic easy later.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from django.db import IntegrityError, transaction

from groups.models import Group
from lanternmail.models import LanternmailList
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
