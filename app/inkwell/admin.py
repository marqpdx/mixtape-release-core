from django.contrib import admin

from inkwell.models import BlacklistedTitle, DeclinedAsset, IngestedFile, SuggestedAsset


# from inkwell.models import BlacklistedTitle, IngestedFile, SuggestedAsset, DeclinedAsset

admin.site.register(IngestedFile)
admin.site.register(SuggestedAsset)
admin.site.register(DeclinedAsset)

@admin.register(BlacklistedTitle)
class BlacklistedTitleAdmin(admin.ModelAdmin):
    list_display = ("loose_title", "reason", "created_at")
    search_fields = ("loose_title", "reason")
