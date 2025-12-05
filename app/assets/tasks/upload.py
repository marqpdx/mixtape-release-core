# assets/tasks/upload.py

# from mixtape.storage_backends import SeaweedStorage
from celery import shared_task
from django.core.files.base import ContentFile

# from django.core.files.storage import default_storage
from storages.backends.s3boto3 import S3Boto3Storage

from assets.models import Asset, GroupAsset


@shared_task
def upload_group_asset_task(asset_id, file_content, s3_key):
    try:
        asset = Asset.objects.get(id=asset_id)

        # Use explicit S3 storage (same as entity images)
        s3_storage = S3Boto3Storage()
        print(f"[CELERY] Using storage type: {type(s3_storage)}")
        print(f"[CELERY] Uploading {s3_key}")

        # Upload using S3 storage
        saved_path = s3_storage.save(s3_key, ContentFile(file_content))
        print(f"[CELERY] Saved to: {saved_path}")

        # Update asset with success
        asset.file_path = saved_path
        asset.upload_status = "completed"
        asset.save()

        # Update GroupAsset
        GroupAsset.objects.filter(asset=asset).update(is_deleted=False)

        return saved_path

    except Exception as e:
        print(f"[CELERY ERROR] Failed to upload: {str(e)}")
        # Handle upload failure
        Asset.objects.filter(id=asset_id).update(upload_status="failed")
        raise e
