# mixtape/storage_backends.py

from storages.backends.s3boto3 import S3Boto3Storage


class PublicMediaStorage(S3Boto3Storage):
    """
    Storage for content that is genuinely public — visible to anyone who
    can already see the page it's attached to (profile avatars/backgrounds,
    group banners, sponsor images). Unlike the default storage (which
    signs every URL), this issues stable, unsigned URLs so next/image can
    fully optimize them and pages can cache them without a TTL race.

    Requires a bucket/MinIO policy granting anonymous GetObject on the
    `public/` location — see
    features/image-handling/image-handling-build-plan.md (puddlejump).

    Do not use this for anything access-controlled. See
    reference/patterns/image-handling-cheatsheet.md (puddlejump) for the
    public vs. access-controlled decision this class assumes has already
    been made for whatever field uses it.
    """

    querystring_auth = False
    location = "public"


# # mixtape/storage_backends.py
# from django.core.files.storage import Storage
# from django.core.files.base import ContentFile
# from django.conf import settings
# import requests

# class SeaweedStorage(Storage):
#     base_url = "http://localhost:8888"
#     bucket_name = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'mixtape-assets')

#     def _save(self, name, content):
#         # Add bucket prefix to the path
#         full_path = f"{self.bucket_name}/{name}"
#         files = {"file": content}
#         response = requests.post(f"{self.base_url}/{full_path}", files=files)
#         if response.status_code not in (200, 201):
#             raise Exception(f"Upload to SeaweedFS failed: {response.status_code} - {response.text}")
#         return name  # Return original name, not full_path

#     def exists(self, name):
#         full_path = f"{self.bucket_name}/{name}"
#         response = requests.head(f"{self.base_url}/{full_path}")
#         return response.status_code == 200

#     def url(self, name):
#         full_path = f"{self.bucket_name}/{name}"
#         return f"{self.base_url}/{full_path}"

#     def open(self, name, mode='rb'):
#         full_path = f"{self.bucket_name}/{name}"
#         response = requests.get(f"{self.base_url}/{full_path}")
#         if response.status_code != 200:
#             raise FileNotFoundError(f"File not found: {name}")
#         return ContentFile(response.content)



# # class SeaweedStorage(Storage):
# #     base_url = "http://localhost:8888"

# #     def _save(self, name, content):
# #         files = {"file": content}
# #         response = requests.post(f"{self.base_url}/{name}", files=files)
# #         if response.status_code not in (200, 201):
# #             raise Exception(f"Upload to SeaweedFS failed: {response.status_code} - {response.text}")
# #         return name

# #     def exists(self, name):
# #         response = requests.head(f"{self.base_url}/{name}")
# #         return response.status_code == 200

# #     def url(self, name):
# #         return f"{self.base_url}/{name}"

# #     def open(self, name, mode='rb'):
# #         response = requests.get(f"{self.base_url}/{name}")
# #         if response.status_code != 200:
# #             raise FileNotFoundError(f"File not found: {name}")
# #         return ContentFile(response.content)
