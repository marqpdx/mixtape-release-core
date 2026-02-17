# lanternmail/services/listmonk_client.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.conf import settings

from .exceptions import (
    ListmonkAuthError,
    ListmonkBadRequestError,
    ListmonkNotFoundError,
    ListmonkUpstreamError,
)


Json = Dict[str, Any]


@dataclass
class ListmonkClient:
    base_url: str
    auth: Tuple[str, str]
    timeout: int = 10

    def __post_init__(self) -> None:
        # Reuse TCP connections; huge for perf + avoids re-handshakes.
        self._session = requests.Session()
        self._session.auth = self.auth

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _req(self, method: str, path: str, **kwargs) -> Json:
        try:
            r = self._session.request(
                method,
                self._url(path),
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as e:
            raise ListmonkUpstreamError(message=f"Listmonk request failed: {e}") from e

        if 200 <= r.status_code < 300:
            # listmonk always returns JSON
            return r.json()

        # Normalize errors (and preserve the body).
        body = r.text
        msg = None
        try:
            msg = r.json().get("message")
        except Exception:
            msg = None

        message = msg or f"Listmonk error ({r.status_code})"

        if r.status_code in (401, 403):
            raise ListmonkAuthError(message=message, status_code=r.status_code, response_text=body)
        if r.status_code == 404:
            raise ListmonkNotFoundError(message=message, status_code=r.status_code, response_text=body)
        if r.status_code == 400:
            raise ListmonkBadRequestError(message=message, status_code=r.status_code, response_text=body)

        raise ListmonkUpstreamError(message=message, status_code=r.status_code, response_text=body)

    # ----------------------------
    # Lists
    # ----------------------------
    def create_list(
        self,
        name: str,
        list_type: str = "private",
        optin: str = "double",
        tags: Optional[List[str]] = None,
        description: str = "",
    ) -> Json:
        payload = {
            "name": name,
            "type": list_type,
            "optin": optin,
            "tags": tags or [],
            "description": description,
        }
        return self._req("POST", "/api/lists", json=payload)

    def get_list(self, list_id: int) -> Json:
        return self._req("GET", f"/api/lists/{list_id}")

    def list_lists(self, query: str = "", per_page: int = 20, page: int = 1) -> Json:
        return self._req("GET", "/api/lists", params={"query": query, "per_page": per_page, "page": page})

    # ----------------------------
    # Subscribers
    # ----------------------------
    def create_subscriber(
        self,
        email: str,
        name: str = "",
        status: str = "enabled",
        attribs: Optional[Dict[str, Any]] = None,
        lists: Optional[List[int]] = None,
        preconfirm_subscriptions: bool = True,
    ) -> Json:
        payload: Json = {
            "email": email,
            "name": name,
            "status": status,
            "attribs": attribs or {},
        }
        if lists:
            payload["lists"] = lists
            payload["preconfirm_subscriptions"] = preconfirm_subscriptions
        return self._req("POST", "/api/subscribers", json=payload)

    def search_subscribers(self, query: str, per_page: int = 100, page: int = 1) -> Json:
        return self._req("GET", "/api/subscribers", params={"query": query, "per_page": per_page, "page": page})

    def update_subscriber_lists(
        self,
        subscriber_id: int,
        add: Optional[List[int]] = None,
        remove: Optional[List[int]] = None,
        status: str = "confirmed",
    ) -> Json:
        resp: Json = {"data": None}

        if add:
            payload = {
                "ids": [subscriber_id],
                "action": "add",
                "target_list_ids": add,
                "status": status,
            }
            resp = self._req("PUT", "/api/subscribers/lists", json=payload)

        if remove:
            payload2 = {
                "ids": [subscriber_id],
                "action": "remove",
                "target_list_ids": remove,
            }
            resp = self._req("PUT", "/api/subscribers/lists", json=payload2)

        return resp

    # ----------------------------
    # Campaigns
    # ----------------------------
    def create_campaign(
        self,
        name: str,
        subject: str,
        list_ids: List[int],
        body: str,
        content_type: str = "richtext",
        messenger: str = "email",
        tags: Optional[List[str]] = None,
    ) -> Json:
        payload = {
            "name": name,
            "subject": subject,
            "lists": list_ids,
            "content_type": content_type,
            "body": body,
            "messenger": messenger,
            "tags": tags or [],
        }
        return self._req("POST", "/api/campaigns", json=payload)

    def get_campaign(self, campaign_id: int) -> Json:
        return self._req("GET", f"/api/campaigns/{campaign_id}")

    def list_campaigns(self, list_id: Optional[int] = None, per_page: int = 20, page: int = 1) -> Json:
        params: Json = {"per_page": per_page, "page": page}
        if list_id is not None:
            params["list_id"] = list_id
        return self._req("GET", "/api/campaigns", params=params)

    def test_campaign(self, campaign_id: int, subscribers: List[str]) -> Json:
        # Your build requires a full campaign payload + subscribers.
        camp = self.get_campaign(campaign_id)["data"]

        payload = {
            "name": camp["name"],
            "subject": camp["subject"],
            "lists": [l["id"] for l in camp.get("lists", [])],
            "content_type": camp.get("content_type", "richtext"),
            "body": camp.get("body", ""),
            "messenger": camp.get("messenger") or "email",
            "subscribers": subscribers,
        }
        return self._req("POST", f"/api/campaigns/{campaign_id}/test", json=payload)

    def update_campaign_status(self, campaign_id: int, status: str) -> Json:
        payload = {"status": status}
        return self._req("PUT", f"/api/campaigns/{campaign_id}/status", json=payload)


def get_listmonk_client() -> ListmonkClient:
    return ListmonkClient(
        base_url=settings.LISTMONK_BASE_URL,
        auth=(settings.LISTMONK_API_USER, settings.LISTMONK_API_TOKEN),
        timeout=getattr(settings, "LISTMONK_TIMEOUT", 10),
    )





# # lanternmail/services/listmonk_client.py

# from __future__ import annotations

# from dataclasses import dataclass
# from typing import Any, Dict, List, Optional, Tuple

# import requests
# from django.conf import settings


# @dataclass(frozen=True)
# class ListmonkClient:
#     base_url: str
#     auth: Tuple[str, str]
#     timeout: int = 10

#     def _url(self, path: str) -> str:
#         return f"{self.base_url.rstrip('/')}{path}"

#     def _req(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
#         r = requests.request(
#             method,
#             self._url(path),
#             auth=self.auth,
#             timeout=self.timeout,
#             **kwargs,
#         )
#         try:
#             r.raise_for_status()
#         except requests.HTTPError as e:
#             # include response text to see listmonk's validation error
#             raise requests.HTTPError(f"{e}\nResponse: {r.text}", response=r) from e
#         return r.json()

#     def _get_campaign(self, campaign_id: int) -> dict:
#         return self._req("GET", f"/api/campaigns/{campaign_id}")


#     # 1) Create list
#     def create_list(
#         self,
#         name: str,
#         list_type: str = "private",
#         optin: str = "double",
#         tags: Optional[List[str]] = None,
#         description: str = "",
#     ) -> Dict[str, Any]:
#         payload = {
#             "name": name,
#             "type": list_type,   # private|public
#             "optin": optin,      # single|double
#             "tags": tags or [],
#             "description": description,
#         }
#         return self._req("POST", "/api/lists", json=payload)

#     # 2) Create subscriber
#     def create_subscriber(
#         self,
#         email: str,
#         name: str = "",
#         status: str = "enabled",
#         attribs: Optional[Dict[str, Any]] = None,
#         lists: Optional[List[int]] = None,
#         preconfirm_subscriptions: bool = True,
#     ) -> Dict[str, Any]:
#         payload = {
#             "email": email,
#             "name": name,
#             "status": status,
#             "attribs": attribs or {},
#         }
#         if lists:
#             payload["lists"] = lists
#             payload["preconfirm_subscriptions"] = preconfirm_subscriptions
#         return self._req("POST", "/api/subscribers", json=payload)

#     # 3) Add/remove subscriber to/from lists
#     def update_subscriber_lists(
#         self,
#         subscriber_id: int,
#         add: Optional[List[int]] = None,
#         remove: Optional[List[int]] = None,
#         status: str = "confirmed",
#     ) -> Dict[str, Any]:
#         payload = {
#             "ids": [subscriber_id],
#             "action": "add",
#             "target_list_ids": add or [],
#             "status": status,  # confirmed|unconfirmed etc (depends on list settings)
#         }
#         # If removing, call twice (keeps it simple + explicit)
#         resp = self._req("PUT", "/api/subscribers/lists", json=payload) if add else {"data": None}
#         if remove:
#             payload2 = {
#                 "ids": [subscriber_id],
#                 "action": "remove",
#                 "target_list_ids": remove,
#             }
#             resp = self._req("PUT", "/api/subscribers/lists", json=payload2)
#         return resp

#     # 4) Create a campaign + test-send to specific emails
#     def create_campaign(
#         self,
#         name: str,
#         subject: str,
#         list_ids: List[int],
#         body: str,
#         content_type: str = "richtext",
#         messenger: str = "email",
#         tags: Optional[List[str]] = None,
#     ) -> Dict[str, Any]:
#         payload = {
#             "name": name,
#             "subject": subject,
#             "lists": list_ids,
#             "content_type": content_type,
#             "body": body,
#         }
#         return self._req("POST", "/api/campaigns", json=payload)

#     # def test_campaign(
#     #     self,
#     #     campaign_id: int,
#     #     subscribers: List[str],
#     # ) -> Dict[str, Any]:
#     #     payload = {
#     #         "subscribers": subscribers,
#     #     }
#     #     return self._req("POST", f"/api/campaigns/{campaign_id}/test", json=payload)

#     def test_campaign(self, campaign_id: int, subscribers: list[str]) -> dict:
#         camp = self._get_campaign(campaign_id)["data"]

#         payload = {
#             # required core campaign fields
#             "name": camp["name"],
#             "subject": camp["subject"],
#             "lists": [l["id"] for l in camp.get("lists", [])],
#             "content_type": camp.get("content_type", "richtext"),
#             "body": camp.get("body", ""),

#             # required for /test in your build
#             "messenger": camp.get("messenger") or "email",

#             # the actual test recipients
#             "subscribers": subscribers,
#         }

#         return self._req("POST", f"/api/campaigns/{campaign_id}/test", json=payload)






# def get_listmonk_client() -> ListmonkClient:
#     return ListmonkClient(
#         base_url=settings.LISTMONK_BASE_URL,
#         auth=(settings.LISTMONK_API_USER, settings.LISTMONK_API_TOKEN),
#         timeout=getattr(settings, "LISTMONK_TIMEOUT", 10),
#     )
