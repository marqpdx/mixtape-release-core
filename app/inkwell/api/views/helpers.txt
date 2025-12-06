# ai/views/helpers.py

from inkwell.models import DeclinedAsset, DeletedAsset


def filter_suggested_assets_by_status(queryset, status: str):
    if status == "approved":
        return queryset.filter(approved=True)
    if status == "in_process":
        return queryset.filter(approved=True, retrieved=False)
    if status == "suggested":
        return queryset.filter(approved=False, retrieved=False)
    if status == "declined":
        return queryset.filter(id__in=DeclinedAsset.objects.values("suggested_asset_id"))
    if status == "deleted":
        return queryset.filter(id__in=DeletedAsset.objects.values("suggested_asset_id"))
    return queryset  # fallback: no filter
