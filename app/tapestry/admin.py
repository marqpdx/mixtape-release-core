from django.contrib import admin

from .models import Location, Place


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["address", "latitude", "longitude", "created_at"]
    search_fields = ["address"]


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ["name", "location", "created_at"]
    search_fields = ["name", "location__address"]
