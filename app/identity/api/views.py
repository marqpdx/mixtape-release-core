# apps/identity/api/views.py

from django.contrib.contenttypes.models import ContentType
from rest_framework import permissions, generics, mixins
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import PermissionDenied

import uuid
import time
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from storages.backends.s3boto3 import S3Boto3Storage



from identity.models import EmblemAvatar, EmblemAvatarType
from .serializers import EmblemAvatarListSerializer, EmblemAvatarTypeSerializer, EmblemAvatarSerializer


# --- Pagination (optional: reuse your global one) ---
class SmallPage(PageNumberPagination):
    page_size = 24
    page_size_query_param = "page_size"
    max_page_size = 100


# --- Permissions ---
class IsSponsorOrReadOnly(permissions.BasePermission):
    """
    Read for anyone allowed by the view; writes only for the sponsor (owner).
    """
    def has_object_permission(self, request, view, obj: EmblemAvatar):
        if request.method in permissions.SAFE_METHODS:
            return True
        sponsor = obj.sponsor  # GenericFK
        return request.user.is_authenticated and sponsor == request.user


# --- Types ---
class EmblemAvatarTypeListAPIView(generics.ListAPIView):
    queryset = EmblemAvatarType.objects.all().order_by("engine", "style")
    serializer_class = EmblemAvatarTypeSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None  # small, finite list


# --- Public gallery ---
class EmblemAvatarPublicListAPIView(generics.ListAPIView):
    serializer_class = EmblemAvatarListSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = EmblemAvatar.objects.filter(is_unlisted=False)
        engine = self.request.query_params.get("engine")
        style  = self.request.query_params.get("style")
        if engine: qs = qs.filter(type__engine=engine)
        if style:  qs = qs.filter(type__style=style)
        return qs.order_by("-updated_at")


# --- Mine (sponsored by current user) ---
class EmblemAvatarMineListAPIView(generics.ListAPIView):
    serializer_class = EmblemAvatarListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = SmallPage

    def get_queryset(self):
        user = self.request.user
        ct = ContentType.objects.get_for_model(user)
        return (
            EmblemAvatar.objects
            .select_related("type")
            .filter(sponsor_content_type=ct, sponsor_object_id=user.pk)
            .order_by("-updated_at")
        )

# --- Create (ensure sponsor) ---
class EmblemAvatarCreateAPIView(generics.CreateAPIView):
    serializer_class = EmblemAvatarSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        user = self.request.user
        ct = ContentType.objects.get_for_model(user)
        serializer.save(sponsor_content_type=ct, sponsor_object_id=user.pk)


# --- Detail / Update / Delete ---
class EmblemAvatarDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = EmblemAvatar.objects.all()
    serializer_class = EmblemAvatarSerializer
    permission_classes = [permissions.IsAuthenticated & IsSponsorOrReadOnly]






class EmblemImageUploadView(APIView):
    """
    Handles emblem image uploads - reuses same pattern as EntityImageUploadView.
    Saves file directly to SeaweedFS (S3-compatible storage) and returns a signed URL.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return Response(
                {"error": "No file provided."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Better file extension handling
        ext = file.name.split(".")[-1] if "." in file.name else ""
        unique_filename = f"{uuid.uuid4()}.{ext}" if ext else str(uuid.uuid4())

        # Path structure: emblem-uploads/<user_id>/<filename>
        # (Will be processed into emblems/<emblem_id>/size_X.png by EmblemRenderer)
        user_id = request.user.id
        s3_key = f"emblem-uploads/{user_id}/{unique_filename}"

        print(f"[EMBLEM UPLOAD] Received {file.name} ({file.size} bytes) for {s3_key}")

        try:
            start = time.time()

            # Use S3 storage (SeaweedFS)
            s3_storage = S3Boto3Storage()

            # Reset file pointer to beginning
            file.seek(0)

            # Save to storage
            saved_path = s3_storage.save(s3_key, file)

            print(f"[EMBLEM UPLOAD] Save took {time.time() - start:.2f}s")
            print(f"[EMBLEM UPLOAD] Saved to path: {saved_path}")

            # Generate signed URL
            public_url = s3_storage.url(saved_path)
            print(f"[EMBLEM UPLOAD] Generated URL: {public_url}")

            return Response({
                "url": public_url,
                "path": saved_path
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            print(f"[EMBLEM UPLOAD ERROR] Failed to save {s3_key}: {str(e)}")
            return Response(
                {"error": f"Upload failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
