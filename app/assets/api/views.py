# mixtape/assets/api/views.py

import time
import uuid, io

from storages.backends.s3boto3 import S3Boto3Storage
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from rest_framework.parsers import MultiPartParser, FormParser
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.core.files.base import ContentFile
from groups.models import Group
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.utils.text import get_valid_filename
from PIL import Image, UnidentifiedImageError
from rest_framework.views import APIView

from assets.api.serializers import AssetSerializer, GroupAssetSerializer, GroupAssetUploadSerializer
from assets.models import Asset, GroupAsset, ProfileAsset
from assets.tasks import upload_group_asset_task
from groups.models import Group

class AssetListCreateView(generics.ListCreateAPIView):
    """
    List all assets for a given object, or create a new asset.
    """
    serializer_class = AssetSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Filter assets to only those belonging to a specific content object
        based on query params:
            ?content_type=<model> & object_id=<id>
        """
        queryset = Asset.objects.all()

        content_type_str = self.request.query_params.get("content_type")
        object_id = self.request.query_params.get("object_id")

        if content_type_str and object_id:
            try:
                ct = ContentType.objects.get(app_label="groups", model=content_type_str)
                queryset = queryset.filter(content_type=ct, object_id=object_id)
            except ContentType.DoesNotExist:
                queryset = Asset.objects.none()

        return queryset

    def perform_create(self, serializer):
        """
        Handle creation logic. We might add extra validation here later.
        """
        serializer.save()


class AssetRetrieveUpdateView(generics.RetrieveUpdateAPIView):
    """
    Retrieve or update a single asset by UUID.
    """
    serializer_class = AssetSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Asset.objects.all()
    lookup_field = "id"


class GroupAssetPresignView(APIView):
    """
    DEPRECATED: Use SponsorAssetPresignView instead.

    Legacy group-specific presign endpoint.
    """
    def get(self, request, group_asset_id):
        group_asset = get_object_or_404(GroupAsset, pk=group_asset_id)
        asset = group_asset.asset
        user = request.user

        # Privacy enforcement (keep your existing logic)
        if asset.privacy == "public":
            pass
        elif asset.privacy == "partners":
            if not user.is_authenticated:
                return Response(status=status.HTTP_403_FORBIDDEN)
        elif asset.privacy == "members":
            if not user.is_authenticated:
                return Response(status=status.HTTP_403_FORBIDDEN)
            if user.is_superuser:
                pass
            elif group_asset.group in user.groups.all():
                pass
            elif hasattr(user, "is_admin_of") and user.is_admin_of(group_asset.group):
                pass
            else:
                return Response(status=status.HTTP_403_FORBIDDEN)
        elif asset.privacy == "admins":
            if not user.is_authenticated or not user.is_admin_of(group_asset.group):
                return Response(status=status.HTTP_403_FORBIDDEN)

        # Generate signed URL using default storage
        # presigned_url = default_storage.url(asset.file_path)

        # Use explicit S3 storage for signed URLs
        from storages.backends.s3boto3 import S3Boto3Storage
        s3_storage = S3Boto3Storage()
        print("GroupAssetPresignView: ",type(s3_storage))  # should be storages.backends.s3boto3.S3Boto3Storage

        presigned_url = s3_storage.url(asset.file_path)

        return Response({"url": presigned_url})


class GroupAssetUploadView(APIView):
    """
    DEPRECATED: Use SponsorAssetUploadView instead.

    Legacy group-specific upload endpoint.
    Kept for backward compatibility.
    """
    def post(self, request, group_id):
        serializer = GroupAssetUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        group = get_object_or_404(Group, pk=group_id)

        uploaded_file = serializer.validated_data["file"]
        privacy = serializer.validated_data.get("privacy", "members")
        asset_type = serializer.validated_data.get("type", "document")

        # Generate a unique filename
        ext = uploaded_file.name.split(".")[-1] if "." in uploaded_file.name else ""
        unique_filename = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())

        folder_path = serializer.validated_data.get("folder_path", "")
        if folder_path and not folder_path.endswith("/"):
            folder_path += "/"

        s3_key = f"groups/{group.id}/uploads/{folder_path}{unique_filename}"

        # Save Asset record with queued status
        asset = Asset.objects.create(
            type=asset_type,
            content_type=ContentType.objects.get_for_model(Group),
            object_id=group.id,
            file_path=s3_key,
            file_name=uploaded_file.name,
            file_type=uploaded_file.content_type,
            file_size=uploaded_file.size,
            privacy=privacy,
            folder_path=folder_path,
            upload_status="queued",  # Set initial status
        )

        group_asset = GroupAsset.objects.create(
            asset=asset,
            group=group,
            uploaded_by=request.user if request.user.is_authenticated else None,
            title=serializer.validated_data.get("title", ""),
            description=serializer.validated_data.get("description", ""),
        )

        # Read file content once
        uploaded_file.seek(0)  # Reset file pointer
        file_content = uploaded_file.read()

        # Dispatch Celery task with simplified parameters
        upload_group_asset_task.delay(
            asset.id,
            file_content,
            s3_key,
        )

        response_data = GroupAssetSerializer(group_asset).data
        response_data["upload_status"] = "queued"

        return Response(response_data, status=status.HTTP_202_ACCEPTED)


class GroupAssetListView(generics.ListAPIView):
    """
    DEPRECATED: Use SponsorAssetListView instead.

    Legacy group-specific asset list endpoint.
    """
    serializer_class = GroupAssetSerializer

    def get_queryset(self):
        group_id = self.kwargs["group_id"]
        return GroupAsset.objects.filter(group_id=group_id, is_deleted=False)


class GroupAssetFolderListView(APIView):
    """
    DEPRECATED: Use SponsorAssetFolderListView instead.

    Legacy group-specific folder list endpoint.
    """
    def get(self, request, group_id):
        folders_qs = (
            GroupAsset.objects
            .filter(group_id=group_id, is_deleted=False)
            .values_list("asset__folder_path", flat=True)
            .distinct()
        )

        # Remove nulls and empty strings
        folder_paths = sorted([
            f for f in folders_qs if f
        ])

        return JsonResponse(folder_paths, safe=False)



ALLOWED_ENTITY_TYPES = {"group", "profile"}          # extend if needed
ALLOWED_IMAGE_TYPES = {"profile", "background", "avatar"}  # extend if needed
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB

class SponsorImageUploadView(APIView):
    """
    Sponsor-agnostic image upload endpoint.

    POST /api/assets/upload?sponsor_type=group&sponsor_id={uuid}&role=profile_image

    Returns: {path, url, bytes, elapsed}
    Store 'path' in DB, derive 'url' at read-time for signed URLs.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        # 1) Get query params
        sponsor_type = request.query_params.get('sponsor_type')
        sponsor_id = request.query_params.get('sponsor_id')
        role = request.query_params.get('role')  # e.g., 'profile_image', 'background_image'

        # 2) Validate params
        if not sponsor_type or sponsor_type not in ['group', 'member']:
            return Response({"error": "Invalid or missing sponsor_type (must be 'group' or 'member')"}, status=400)
        if not sponsor_id:
            return Response({"error": "Missing sponsor_id"}, status=400)
        if not role:
            return Response({"error": "Missing role parameter"}, status=400)

        # 3) Verify sponsor exists and user has permission
        try:
            if sponsor_type == 'group':
                from groups.models import Group
                sponsor = Group.objects.get(id=sponsor_id)
                # TODO: Add permission check - user must be admin/member
                # if not sponsor.user_can_edit(request.user):
                #     return Response({"error": "Permission denied"}, status=403)
            elif sponsor_type == 'member':
                from users.models import User
                sponsor = User.objects.get(id=sponsor_id)
                # User can only upload to their own profile
                if str(sponsor.id) != str(request.user.id) and not request.user.is_staff:
                    return Response({"error": "Permission denied"}, status=403)
        except Exception as e:
            return Response({"error": f"Sponsor not found: {str(e)}"}, status=404)


        print("*** SponsorImageUploadView: sponsor_type=",sponsor_type,"sponsor_id=",sponsor_id)
        # 4) Get and validate file
        f = request.FILES.get("file")
        if not f:
            return Response({"error": "No file provided"}, status=400)
        if f.size > MAX_UPLOAD_BYTES:
            return Response({"error": f"File too large (max {MAX_UPLOAD_BYTES/1024/1024}MB)"}, status=413)

        # 5) Normalize filename and build S3 key
        base = get_valid_filename(f.name or "")
        ext = (base.rsplit(".", 1)[-1].lower() if "." in base else "")
        unique = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())

        # Use sponsor type plural for path consistency
        sponsor_path = 'groups' if sponsor_type == 'group' else 'members'
        s3_key = f"{sponsor_path}/{sponsor_id}/{role}/{unique}"


        print("*** SponsorImageUploadView: generated s3_key:", s3_key)


        # 6) Verify it's an image
        try:
            buf = f.read()
            img = Image.open(io.BytesIO(buf))
            img.verify()
            payload = buf
        except (UnidentifiedImageError, OSError):
            return Response({"error": "Unsupported or corrupt image"}, status=400)


        print("*** SponsorImageUploadView: image verified, size:", len(payload))
        print("*** SponsorImageUploadView: scheduling upload to S3 key:", s3_key)
        print("*** SponsorImageUploadView: file size bytes:", len(payload))
        print("*** SponsorImageUploadView: default_storage:", default_storage)


        # 7) Save to storage
        start = time.time()
        saved_key = default_storage.save(s3_key, ContentFile(payload))
        public_url = default_storage.url(saved_key)
        took = time.time() - start

        return Response(
            {
                "path": saved_key,  # Store this in DB
                "url": public_url,  # For immediate display
                "bytes": len(payload),
                "elapsed": round(took, 3),
            },
            status=status.HTTP_201_CREATED,
        )


class SponsorAssetUploadView(APIView):
    """
    Sponsor-agnostic managed asset upload endpoint.
    Creates full Asset + join table records with metadata, privacy, etc.

    POST /api/assets/managed/upload?sponsor_type=group&sponsor_id={uuid}

    Use this for files that need full asset management (documents, media files).
    For simple profile/background images, use /api/assets/upload/ instead.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        from assets.api.serializers import GroupAssetUploadSerializer

        # Get sponsor info from query params
        sponsor_type = request.query_params.get('sponsor_type')
        sponsor_id = request.query_params.get('sponsor_id')

        print("*** SponsorAssetUploadView: sponsor_type=",sponsor_type,"sponsor_id=",sponsor_id)

        # Validate params
        if not sponsor_type or sponsor_type not in ['group', 'profile']:
            return Response({
                "error": "Invalid or missing sponsor_type (must be 'group' or 'profile')"
            }, status=400)
        if not sponsor_id:
            return Response({"error": "Missing sponsor_id"}, status=400)

        # Get and validate sponsor
        try:
            if sponsor_type == 'group':
                sponsor = Group.objects.get(id=sponsor_id)
                # TODO: Add permission check
            elif sponsor_type == 'profile':
                from profiles.models import UserProfile
                sponsor = UserProfile.objects.get(id=sponsor_id)
                # User can only upload to their own profile
                if str(sponsor.user_id) != str(request.user.id) and not request.user.is_staff:
                    return Response({"error": "Permission denied"}, status=403)
        except Exception as e:
            return Response({"error": f"Sponsor not found: {str(e)}"}, status=404)


        print("*** SponsorAssetUploadView: sponsor_type=",sponsor_type,"sponsor_id=",sponsor_id)


        # Validate upload data
        serializer = GroupAssetUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]
        privacy = serializer.validated_data.get("privacy", "members")
        asset_type = serializer.validated_data.get("type", "document")
        folder_path = serializer.validated_data.get("folder_path", "")

        print("*** SponsorAssetUploadView: received file:", uploaded_file.name, "size:", uploaded_file.size)

        if folder_path and not folder_path.endswith("/"):
            folder_path += "/"

        # Generate unique filename
        ext = uploaded_file.name.split(".")[-1] if "." in uploaded_file.name else ""
        unique_filename = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())

        # Build S3 key based on sponsor type
        sponsor_path = f"{sponsor_type}s"  # 'groups' or 'profiles'
        s3_key = f"{sponsor_path}/{sponsor_id}/uploads/{folder_path}{unique_filename}"

        print("*** SponsorAssetUploadView: generated s3_key:", s3_key)
        print("*** SponsorAssetUploadView: privacy:", privacy, "asset_type:", asset_type)


        # Create Asset record
        asset = Asset.objects.create(
            type=asset_type,
            content_type=ContentType.objects.get_for_model(sponsor.__class__),
            object_id=sponsor_id,
            file_path=s3_key,
            file_name=uploaded_file.name,
            file_type=uploaded_file.content_type,
            file_size=uploaded_file.size,
            privacy=privacy,
            folder_path=folder_path,
            upload_status="queued",
        )

        # Create sponsor-specific join table record
        if sponsor_type == 'group':
            join_record = GroupAsset.objects.create(
                asset=asset,
                group=sponsor,
                uploaded_by=request.user if request.user.is_authenticated else None,
                title=serializer.validated_data.get("title", ""),
                description=serializer.validated_data.get("description", ""),
            )
            from assets.api.serializers import GroupAssetSerializer
            response_serializer = GroupAssetSerializer(join_record)
        elif sponsor_type == 'profile':
            join_record = ProfileAsset.objects.create(
                asset=asset,
                profile=sponsor,
                title=serializer.validated_data.get("title", ""),
                description=serializer.validated_data.get("description", ""),
            )
            from assets.api.serializers import ProfileAssetSerializer
            response_serializer = ProfileAssetSerializer(join_record)

        # Read file content and queue upload task
        uploaded_file.seek(0)
        file_content = uploaded_file.read()

        print("*** Scheduling upload task for asset ID:", asset.id)
        upload_group_asset_task.delay(
            asset.id,
            file_content,
            s3_key,
        )

        response_data = response_serializer.data
        response_data["upload_status"] = "queued"

        return Response(response_data, status=status.HTTP_202_ACCEPTED)


class SponsorAssetPresignView(APIView):
    """
    Sponsor-agnostic presigned URL generation for managed assets.

    GET /api/assets/managed/{asset_id}/presign

    Enforces privacy rules and returns a signed URL for accessing the asset.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, asset_id):
        asset = get_object_or_404(Asset, pk=asset_id)
        user = request.user

        # Get the join record to check permissions
        # Try GroupAsset first, then ProfileAsset
        join_record = None
        try:
            join_record = GroupAsset.objects.get(asset=asset)
            sponsor_type = 'group'
            sponsor = join_record.group
        except GroupAsset.DoesNotExist:
            try:
                join_record = ProfileAsset.objects.get(asset=asset)
                sponsor_type = 'profile'
                sponsor = join_record.profile
            except ProfileAsset.DoesNotExist:
                return Response({"error": "Asset join record not found"}, status=404)

        # Privacy enforcement
        if asset.privacy == "public":
            pass
        elif asset.privacy == "partners":
            if not user.is_authenticated:
                return Response(status=status.HTTP_403_FORBIDDEN)
        elif asset.privacy == "members":
            if not user.is_authenticated:
                return Response(status=status.HTTP_403_FORBIDDEN)
            if user.is_superuser:
                pass
            elif sponsor_type == 'group':
                if sponsor in user.groups.all():
                    pass
                elif hasattr(user, "is_admin_of") and user.is_admin_of(sponsor):
                    pass
                else:
                    return Response(status=status.HTTP_403_FORBIDDEN)
            elif sponsor_type == 'profile':
                if str(sponsor.user_id) != str(user.id):
                    return Response(status=status.HTTP_403_FORBIDDEN)
        elif asset.privacy == "admins":
            if not user.is_authenticated:
                return Response(status=status.HTTP_403_FORBIDDEN)
            if sponsor_type == 'group':
                if not user.is_admin_of(sponsor):
                    return Response(status=status.HTTP_403_FORBIDDEN)
            elif sponsor_type == 'profile':
                if str(sponsor.user_id) != str(user.id):
                    return Response(status=status.HTTP_403_FORBIDDEN)

        # Generate signed URL
        s3_storage = S3Boto3Storage()
        presigned_url = s3_storage.url(asset.file_path)

        return Response({"url": presigned_url})


class SponsorAssetListView(APIView):
    """
    Sponsor-agnostic asset list endpoint.

    GET /api/assets/managed/list?sponsor_type=group&sponsor_id={uuid}

    Returns all assets for a given sponsor.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        sponsor_type = request.query_params.get('sponsor_type')
        sponsor_id = request.query_params.get('sponsor_id')

        if not sponsor_type or sponsor_type not in ['group', 'profile']:
            return Response({
                "error": "Invalid or missing sponsor_type (must be 'group' or 'profile')"
            }, status=400)
        if not sponsor_id:
            return Response({"error": "Missing sponsor_id"}, status=400)

        # Get assets based on sponsor type
        if sponsor_type == 'group':
            from assets.api.serializers import GroupAssetSerializer
            assets = GroupAsset.objects.filter(
                group_id=sponsor_id,
                is_deleted=False
            ).select_related('asset', 'group')
            serializer = GroupAssetSerializer(assets, many=True)
        elif sponsor_type == 'profile':
            from assets.api.serializers import ProfileAssetSerializer
            assets = ProfileAsset.objects.filter(
                profile_id=sponsor_id
            ).select_related('asset', 'profile')
            serializer = ProfileAssetSerializer(assets, many=True)

        return Response(serializer.data)


class SponsorAssetFolderListView(APIView):
    """
    Sponsor-agnostic folder list endpoint.

    GET /api/assets/managed/folders?sponsor_type=group&sponsor_id={uuid}

    Returns list of folder paths for a given sponsor's assets.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        sponsor_type = request.query_params.get('sponsor_type')
        sponsor_id = request.query_params.get('sponsor_id')

        if not sponsor_type or sponsor_type not in ['group', 'profile']:
            return Response({
                "error": "Invalid or missing sponsor_type (must be 'group' or 'profile')"
            }, status=400)
        if not sponsor_id:
            return Response({"error": "Missing sponsor_id"}, status=400)

        # Get folder paths based on sponsor type
        if sponsor_type == 'group':
            folders_qs = (
                GroupAsset.objects
                .filter(group_id=sponsor_id, is_deleted=False)
                .values_list("asset__folder_path", flat=True)
                .distinct()
            )
        elif sponsor_type == 'profile':
            folders_qs = (
                ProfileAsset.objects
                .filter(profile_id=sponsor_id)
                .values_list("asset__folder_path", flat=True)
                .distinct()
            )

        # Remove nulls and empty strings
        folder_paths = sorted([f for f in folders_qs if f])

        return JsonResponse(folder_paths, safe=False)


class EntityImageUploadView(APIView):
    """
    DEPRECATED: Use SponsorImageUploadView instead.

    Legacy endpoint for backwards compatibility.
    Uploads an image to S3-compatible storage and returns {url, path}.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, entity_type, entity_id, image_type):
        # 1) Validate route params
        if entity_type not in ALLOWED_ENTITY_TYPES:
            return Response({"error": "Invalid entity_type"}, status=400)
        if image_type not in ALLOWED_IMAGE_TYPES:
            return Response({"error": "Invalid image_type"}, status=400)

        f = request.FILES.get("file")
        if not f:
            return Response({"error": "No file provided"}, status=400)
        if f.size > MAX_UPLOAD_BYTES:
            return Response({"error": "File too large"}, status=413)

        # 2) Normalize filename and build key
        base = get_valid_filename(f.name or "")
        ext = (base.rsplit(".", 1)[-1].lower() if "." in base else "")
        unique = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())
        s3_key = f"{entity_type}s/{entity_id}/{image_type}/{unique}"

        # 3) Verify it's an image (and optionally normalize)
        try:
            # Read into memory once (bounded by MAX_UPLOAD_BYTES)
            buf = f.read()
            img = Image.open(io.BytesIO(buf))
            img.verify()  # quick integrity check

            # Optionally re-encode (controls format/strips metadata):
            # img = Image.open(io.BytesIO(buf)).convert("RGB")
            # out = io.BytesIO(); img.save(out, format="PNG", optimize=True)
            # payload = out.getvalue()

            payload = buf  # if not re-encoding
        except (UnidentifiedImageError, OSError):
            return Response({"error": "Unsupported or corrupt image"}, status=400)

        # 4) Save to storage (KEY, not URL)
        start = time.time()
        saved_key = default_storage.save(s3_key, ContentFile(payload))
        public_url = default_storage.url(saved_key)
        took = time.time() - start

        return Response(
            {
                "path": saved_key,  # <-- store this in DB
                "url": public_url,  # convenient for immediate display
                "bytes": len(payload),
                "elapsed": round(took, 3),
            },
            status=status.HTTP_201_CREATED,
        )