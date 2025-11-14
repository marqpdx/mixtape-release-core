# accounts/api/serializers.py

# from django.shortcuts import get_object_or_404

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
# from django.contrib.auth.models import Group  # Deferred to Phase 3
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
# from storages.backends.s3boto3 import S3Boto3Storage  # Deferred to Phase 2
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.validators import UniqueValidator
from users.models import CustomUser
from uuid import UUID
import importlib
import logging

from profiles.models import UserProfile
from users.models import CustomUser, Role
# from utils.misc import randomword  # Deferred - utils app
# from utils.storage.storage_utils import key_to_url  # Deferred to Phase 2

from .mixins import RoleMixin

logger = logging.getLogger(__name__)

class BaseUserSerializer(RoleMixin, serializers.ModelSerializer):
    """Base serializer to unify User logic"""

    class Meta:
        model = get_user_model()
        fields = [
            "id", "username", "email", "first_name",
            "last_name", "is_active", "is_staff", "is_superuser", "roles"
        ]


# ============================================================================
# DEFERRED: UserProfileSerializerInline (Phase 2 - Image Storage)
# ============================================================================
# This serializer includes S3 image fields that don't exist in Phase 1 UserProfile
# Will uncomment when we add image storage functionality
# ============================================================================
# class UserProfileSerializerInline(serializers.ModelSerializer):
#     profile_image_url = serializers.SerializerMethodField()
#     background_image_url = serializers.SerializerMethodField()
#
#     class Meta:
#         model = UserProfile
#         fields = [
#             "id",
#             "display_name",
#             "profile_image", "background_image",
#             "profile_image_url", "background_image_url",
#             "slug",
#             "quick_intro",
#             "bio_json",
#             "bio_markdown",
#             "avatar",
#             "created_at",
#             "updated_at",
#             "profile_image_visibility",
#             "background_image_visibility",
#         ]
#
#     def get_profile_image_url(self, obj):
#         from utils.storage.storage_utils import key_to_url
#         key = getattr(obj, "profile_image", None) or getattr(obj, "profile_image_path", None)
#         return key_to_url(key)
#
#     def get_background_image_url(self, obj):
#         from utils.storage.storage_utils import key_to_url
#         key = getattr(obj, "background_image", None) or getattr(obj, "background_image_path", None)
#         return key_to_url(key)








# ============================================================================
# DEFERRED: UserSerializer with Profile (Phase 2 - Image Storage)
# ============================================================================
# This serializer includes UserProfileSerializerInline which needs S3 storage
# Will uncomment when we add image storage functionality
# ============================================================================
# class UserSerializer(BaseUserSerializer):
#     profile = UserProfileSerializerInline(read_only=True)
#
#     class Meta(BaseUserSerializer.Meta):
#         model = get_user_model()
#         fields = BaseUserSerializer.Meta.fields + [
#             "date_joined", "last_login", "profile",
#         ]






# ============================================================================
# DEFERRED: GatheringUserSerializer (Phase 3 - Groups/Gatherings)
# ============================================================================
# class GatheringUserSerializer(serializers.ModelSerializer):
#     """
#     Minimal user info for gatherings, with member_role supplied by view/query.
#     """
#     member_role = serializers.CharField()
#
#     class UserProfileSerializerInline(serializers.ModelSerializer):
#         profile_image_url = serializers.SerializerMethodField()
#
#         class Meta:
#             model = UserProfile
#             fields = ["id", "display_name", "profile_image", "profile_image_url"]
#
#         def get_profile_image_url(self, obj):
#             from utils.storage.storage_utils import key_to_url
#             key = getattr(obj, "profile_image", None) or getattr(obj, "profile_image_path", None)
#             return key_to_url(key)
#
#     profile = UserProfileSerializerInline(read_only=True)
#
#     class Meta:
#         model = get_user_model()
#         fields = (
#             "date_joined", "email", "first_name", "id", "is_active",
#             "last_login", "last_name", "username", "profile", "member_role",
#         )



# ============================================================================
# DEFERRED: GroupSerializer (Phase 3 - Groups)
# ============================================================================
# class GroupSerializer(serializers.HyperlinkedModelSerializer):
#     background_image_url = serializers.SerializerMethodField()
#     profile_image_url = serializers.SerializerMethodField()
#
#     class Meta:
#         model = Group
#         fields = ['url', 'name', 'background_image_url', 'profile_image_url']
#
#     def get_background_image_url(self, obj):
#         from utils.storage.storage_utils import key_to_url
#         key = getattr(obj, "background_image_path", None) or getattr(obj, "background_image", None)
#         return key_to_url(key)
#
#     def get_profile_image_url(self, obj):
#         from utils.storage.storage_utils import key_to_url
#         key = getattr(obj, "profile_image_path", None) or getattr(obj, "profile_image", None)
#         return key_to_url(key)
#
#
#
#
#
#
# class GroupSerializer(serializers.HyperlinkedModelSerializer):
#     background_image_url = serializers.SerializerMethodField()
#     profile_image_url = serializers.SerializerMethodField()
#
#     class Meta:
#         model = Group
#         fields = ['url', 'name', "background_image_url", "profile_image_url", ]
#
#     def get_background_image_url(self, obj):
#         if not obj.background_image_path:
#             return None
#         from storages.backends.s3boto3 import S3Boto3Storage
#         storage = S3Boto3Storage()
#         return storage.url(obj.background_image_path)  # presigned, fresh
#
#     def get_profile_image_url(self, obj):
#         if not obj.profile_image_path:
#             return None
#         from storages.backends.s3boto3 import S3Boto3Storage
#         storage = S3Boto3Storage()
#         return storage.url(obj.profile_image_path)  # presigned, fresh







class UserCreateSerializer(serializers.ModelSerializer):

    username = serializers.SlugField(
        min_length=3,
        max_length=32,
        help_text=_(
            'Required. 4-32 characters. Letters, numbers, underscores or hyphens only.'
        ),
        validators=[UniqueValidator(
            queryset=get_user_model().users.all(),
            message='has already been taken by other user'
        )],
        required=True
    )
    password = serializers.CharField(
        min_length=4,
        max_length=32,
        write_only=True,
        help_text=_(
            'Required. 4-32 characters.'
        ),
        required=True
    )
    email = serializers.EmailField(
        required=True,
        validators=[UniqueValidator(
            queryset=get_user_model().users.all(),
            message='has already been taken by other user'
        )]
    )

    # Note, the default fields from django core user model are:
    # username, password, email, first_name, last_name

    class Meta:
        model = get_user_model()
        fields = (
            'username', 'first_name', 'last_name', 'email', 'password'
        )

    def create(self, validated_data):

        username = validated_data['username']
        email = validated_data['email']
        user = get_user_model()(
                username = username, email = email,
                first_name = validated_data['first_name'],
                last_name = validated_data['last_name']
        )
        user.set_password(validated_data['password'])

        # ✅ Assign Default Role: "member"
        member_role, _ = Role.objects.get_or_create(name='member')
        print(f"[Serializer] Role 'member' assigned to {user.username}")
        user.save()
        user.roles.add(member_role)
        user.save()

        profile = UserProfile(
            user = user,
            name = username,
        )
        profile.save()

        return user


# class TokenObtainPairSa


class TokenRefreshSerializer(serializers.Serializer):
    """
    Refresh token serializer that reads from httpOnly cookie.
    Handles missing users gracefully without 500 errors.
    """

    def get_token_from_cookie(self):
        request = self.context["request"]
        return request.COOKIES.get(settings.JWT_COOKIE_NAME)

    def validate(self, attrs):
        # Extract token from cookie
        token = self.get_token_from_cookie()

        if not token:
            logger.warning("Token refresh attempted without cookie")
            raise AuthenticationFailed(
                "No refresh token found",
                code="no_refresh_cookie"
            )

        # Validate token structure and signature
        try:
            refresh = RefreshToken(token)
        except TokenError as e:
            logger.info(f"Invalid refresh token: {e}")
            raise AuthenticationFailed(
                "Invalid or expired refresh token",
                code="invalid_refresh_token"
            )

        # Extract and validate user_id
        user_id = refresh.get("user_id")
        if not user_id:
            logger.error("Refresh token missing user_id claim")
            raise AuthenticationFailed(
                "Invalid token structure",
                code="invalid_token_claims"
            )

        # Lookup user - this is where the 500 was happening
        try:
            user = CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            # 🔥 FIX: Return 401 instead of letting it bubble to 500
            logger.warning(
                f"Token refresh failed: user {user_id} no longer exists. "
                "This is normal in development when database is reset."
            )
            raise AuthenticationFailed(
                "User account no longer exists",
                code="user_not_found"
            )

        # Check if user is active
        if not user.is_active:
            logger.warning(f"Inactive user {user_id} attempted token refresh")
            raise AuthenticationFailed(
                "User account is disabled",
                code="user_inactive"
            )

        # Generate new access token with custom claims
        access = refresh.access_token
        access["username"] = user.username

        # Prepare response data
        data = {
            "access": str(access),
            "access_expires": access["exp"],
            "refresh": str(refresh),
            "refresh_expires": refresh["exp"]
        }

        # Handle token rotation if enabled
        if jwt_settings.ROTATE_REFRESH_TOKENS:
            if jwt_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    refresh.blacklist()
                except AttributeError:
                    logger.warning("Token blacklist not configured")
                    pass

            # Generate new refresh token
            refresh.set_jti()
            refresh.set_exp()
            data["refresh"] = str(refresh)
            data["refresh_expires"] = refresh["exp"]

        return data


class EmailOrUsernameTokenSerializer(serializers.Serializer):
    """
    Login serializer that accepts email or username + password.
    Returns JWT tokens with custom claims.
    """
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs.get("identifier")
        password = attrs.get("password")

        # Normalize identifier to username
        username = identifier
        if "@" in identifier:
            try:
                user = CustomUser.objects.get(email__iexact=identifier.lower())
                username = user.username
                logger.info(f"Login attempt via email for user: {username}")
            except CustomUser.DoesNotExist:
                logger.warning(f"Login failed: no user with email {identifier}")
                raise serializers.ValidationError(
                    "Invalid credentials",
                    code="invalid_credentials"
                )

        # Authenticate
        user = authenticate(username=username, password=password)

        if not user:
            logger.warning(f"Authentication failed for: {username}")
            raise serializers.ValidationError(
                "Invalid credentials",
                code="invalid_credentials"
            )

        if not user.is_active:
            logger.warning(f"Inactive user login attempt: {username}")
            raise serializers.ValidationError(
                "User account is disabled",
                code="user_inactive"
            )

        # Generate tokens
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        # Add custom claims
        access["username"] = user.username

        logger.info(f"Successful login for user: {user.username}")

        return {
            "refresh": str(refresh),
            "refresh_expires": refresh["exp"],
            "access": str(access),
            "access_expires": access["exp"],
            "user": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
            }
        }