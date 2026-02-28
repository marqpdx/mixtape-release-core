from __future__ import annotations

from django.conf import settings
from django.db import models


class FeedbackBeacon(models.Model):
    class Scope(models.TextChoices):
        GLOBAL = "global", "Global"
        ROUTE = "route", "Route"
        COMPONENT = "component", "Component"

    key = models.SlugField(unique=True, max_length=64)
    title = models.CharField(max_length=120)
    body_markdown = models.TextField(blank=True, default="")
    feature_context = models.TextField(blank=True, default="")
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.GLOBAL)
    route_pattern = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.key} ({'active' if self.is_active else 'inactive'})"


class FeedbackItem(models.Model):
    class Kind(models.TextChoices):
        BUG = "bug", "Bug"
        REQUEST = "request", "Request"
        IDEA = "idea", "Idea"
        ISSUE = "issue", "Issue"

    class Status(models.TextChoices):
        NEW = "new", "New"
        TRIAGED = "triaged", "Triaged"
        PLANNED = "planned", "Planned"
        SHIPPED = "shipped", "Shipped"
        WONTFIX = "wontfix", "Won't Fix"

    beacon = models.ForeignKey(FeedbackBeacon, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    message = models.TextField()
    page_url = models.TextField(blank=True, default="")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.beacon.key} • {self.kind} • {self.created_at.date()}"
