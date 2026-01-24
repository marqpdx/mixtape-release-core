# bazaar/admin.py

"""
Django Admin configuration for Bazaar models.
"""

from django.contrib import admin
from django.utils.html import format_html

from bazaar.models import (
    Product,
    BazaarOffering,
    BazaarOrder,
    BazaarFulfillmentEvent,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin for Bazaar Products."""

    list_display = [
        "title",
        "product_type",
        "status",
        "sponsor_display",
        "requires_shipping",
        "created_at",
    ]
    list_filter = ["product_type", "status", "requires_shipping"]
    search_fields = ["title", "summary", "slug"]
    readonly_fields = ["id", "slug", "created_at", "updated_at"]
    date_hierarchy = "created_at"

    fieldsets = (
        (None, {
            "fields": ("title", "summary", "body", "slug")
        }),
        ("Product Details", {
            "fields": ("product_type", "status", "requires_shipping", "primary_file_id")
        }),
        ("Sponsorship", {
            "fields": ("sponsor_content_type", "sponsor_object_id", "author", "submitted_by")
        }),
        ("Metadata", {
            "fields": ("id", "created_at", "updated_at", "published_at"),
            "classes": ("collapse",)
        }),
    )

    def sponsor_display(self, obj):
        return obj.sponsor_display if obj.sponsor else "-"
    sponsor_display.short_description = "Sponsor"


@admin.register(BazaarOffering)
class BazaarOfferingAdmin(admin.ModelAdmin):
    """Admin for Bazaar Offerings."""

    list_display = [
        "title",
        "shape",
        "status",
        "visibility",
        "price_display",
        "sponsor_display",
        "created_at",
    ]
    list_filter = ["shape", "status", "visibility", "fulfillment_type", "is_free"]
    search_fields = ["title", "summary", "slug"]
    readonly_fields = ["id", "slug", "created_at", "updated_at"]
    date_hierarchy = "created_at"

    fieldsets = (
        (None, {
            "fields": ("title", "summary", "body", "slug")
        }),
        ("Offering Details", {
            "fields": ("shape", "status", "visibility")
        }),
        ("Pricing", {
            "fields": ("price_amount", "currency", "is_free", "price_config")
        }),
        ("Fulfillment", {
            "fields": ("fulfillment_type", "fulfillment_config")
        }),
        ("Asset Reference", {
            "fields": ("asset_content_type", "asset_object_id"),
            "classes": ("collapse",)
        }),
        ("Sponsorship", {
            "fields": ("sponsor_content_type", "sponsor_object_id", "author", "submitted_by")
        }),
        ("Metadata", {
            "fields": ("id", "created_at", "updated_at", "published_at"),
            "classes": ("collapse",)
        }),
    )

    def sponsor_display(self, obj):
        return obj.sponsor_display if obj.sponsor else "-"
    sponsor_display.short_description = "Sponsor"

    def price_display(self, obj):
        if obj.is_free:
            return format_html('<span style="color: green;">FREE</span>')
        # Convert from minor units (cents) to display
        amount = obj.price_amount / 100
        return f"{obj.currency} {amount:.2f}"
    price_display.short_description = "Price"


@admin.register(BazaarOrder)
class BazaarOrderAdmin(admin.ModelAdmin):
    """Admin for Bazaar Orders."""

    list_display = [
        "id_short",
        "offering_title",
        "buyer",
        "status",
        "amount_display",
        "created_at",
    ]
    list_filter = ["status", "currency"]
    search_fields = ["id", "buyer__username", "buyer__email", "offering__title"]
    readonly_fields = [
        "id", "created_at", "updated_at",
        "stripe_payment_intent_id", "stripe_charge_id",
        "offering_snapshot",
    ]
    date_hierarchy = "created_at"
    raw_id_fields = ["offering", "buyer"]

    fieldsets = (
        (None, {
            "fields": ("id", "offering", "buyer", "status")
        }),
        ("Payment", {
            "fields": ("amount", "currency")
        }),
        ("Notes", {
            "fields": ("buyer_note", "vendor_note")
        }),
        ("Stripe", {
            "fields": ("stripe_payment_intent_id", "stripe_charge_id"),
            "classes": ("collapse",)
        }),
        ("Audit", {
            "fields": ("offering_snapshot", "created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )

    def id_short(self, obj):
        return str(obj.id)[:8] + "..."
    id_short.short_description = "ID"

    def offering_title(self, obj):
        return obj.offering.title if obj.offering else "-"
    offering_title.short_description = "Offering"

    def amount_display(self, obj):
        amount = obj.amount / 100
        return f"{obj.currency} {amount:.2f}"
    amount_display.short_description = "Amount"

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of orders via admin."""
        return False


@admin.register(BazaarFulfillmentEvent)
class BazaarFulfillmentEventAdmin(admin.ModelAdmin):
    """Admin for Bazaar Fulfillment Events."""

    list_display = [
        "id_short",
        "order_id_short",
        "event_type",
        "actor_type",
        "actor_user",
        "created_at",
    ]
    list_filter = ["event_type", "actor_type"]
    search_fields = ["order__id", "notes"]
    readonly_fields = ["id", "created_at", "updated_at"]
    date_hierarchy = "created_at"
    raw_id_fields = ["order", "actor_user"]

    def id_short(self, obj):
        return str(obj.id)[:8] + "..."
    id_short.short_description = "ID"

    def order_id_short(self, obj):
        return str(obj.order_id)[:8] + "..."
    order_id_short.short_description = "Order"
