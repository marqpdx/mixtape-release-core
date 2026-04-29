from django.contrib import admin

from .models import FixItem, Supplier, SupplyRequest


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "sponsor_object_id", "created_at")
    search_fields = ("name", "contact_info")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(SupplyRequest)
class SupplyRequestAdmin(admin.ModelAdmin):
    list_display = ("item_name", "quantity_note", "supplier", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("item_name",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(FixItem)
class FixItemAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "sponsor_object_id", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "description")
    readonly_fields = ("id", "created_at", "updated_at")
