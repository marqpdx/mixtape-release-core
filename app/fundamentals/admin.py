# fundamentals/admin.py

from django.contrib import admin

from fundamentals.models import Follow


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ["id", "follower", "following", "created_at"]
    raw_id_fields = ["follower", "following"]
