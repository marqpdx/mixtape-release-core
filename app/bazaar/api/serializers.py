# bazaar/api/serializers.py

"""
Bazaar API Serializers

Serializers for Bazaar models with read/write variants.
"""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from bazaar.constants import (
    FulfillmentType,
    OfferingShape,
    OfferingStatus,
    OfferingVisibility,
    OrderStatus,
    ProductStatus,
    ProductType,
)
from bazaar.models import (
    BazaarFulfillmentEvent,
    BazaarOffering,
    BazaarOrder,
    Product,
)


User = get_user_model()


# =============================================================================
# Helper Serializers
# =============================================================================

class SponsorSerializer(serializers.Serializer):
    """Read-only serializer for polymorphic sponsor display."""
    id = serializers.UUIDField(source="sponsor_object_id", read_only=True)
    type = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()

    def get_type(self, obj):
        if obj.sponsor_content_type:
            return obj.sponsor_content_type.model
        return None

    def get_display_name(self, obj):
        return obj.sponsor_display if hasattr(obj, "sponsor_display") else str(obj.sponsor)


class BuyerSerializer(serializers.ModelSerializer):
    """Read-only serializer for buyer display."""
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "display_name"]
        read_only_fields = fields

    def get_display_name(self, obj):
        if hasattr(obj, "profile") and obj.profile:
            return obj.profile.display_name or obj.username
        return obj.get_full_name() or obj.username


# =============================================================================
# Product Serializers
# =============================================================================

class ProductListSerializer(serializers.ModelSerializer):
    """Serializer for product list view (minimal fields)."""
    sponsor = SponsorSerializer(source="*", read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "title",
            "slug",
            "summary",
            "product_type",
            "status",
            "sponsor",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]


class ProductDetailSerializer(serializers.ModelSerializer):
    """Serializer for product detail view (all fields)."""
    sponsor = SponsorSerializer(source="*", read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "title",
            "slug",
            "summary",
            "body",
            "product_type",
            "status",
            "requires_shipping",
            "primary_file_id",
            "sponsor",
            "published_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]


class ProductCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating products."""
    sponsor_type = serializers.CharField(write_only=True, help_text="Model name: 'group' or 'user'")
    sponsor_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = Product
        fields = [
            "title",
            "summary",
            "body",
            "product_type",
            "requires_shipping",
            "primary_file_id",
            "sponsor_type",
            "sponsor_id",
        ]

    def validate(self, attrs):
        sponsor_type = attrs.pop("sponsor_type")
        sponsor_id = attrs.pop("sponsor_id")

        # Resolve sponsor
        try:
            ct = ContentType.objects.get(model=sponsor_type.lower())
            sponsor = ct.get_object_for_this_type(pk=sponsor_id)
        except (ContentType.DoesNotExist, Exception) as e:
            raise serializers.ValidationError({"sponsor_type": f"Invalid sponsor: {e}"})

        attrs["_sponsor"] = sponsor
        return attrs

    def create(self, validated_data):
        sponsor = validated_data.pop("_sponsor")
        user = self.context["request"].user

        product = Product(**validated_data)
        product.set_sponsor(sponsor)
        product.submitted_by = user
        product.author = user
        product.save()

        return product


# =============================================================================
# Offering Serializers
# =============================================================================

class OfferingListSerializer(serializers.ModelSerializer):
    """Serializer for offering list view."""
    sponsor = SponsorSerializer(source="*", read_only=True)
    effective_price = serializers.IntegerField(read_only=True)

    class Meta:
        model = BazaarOffering
        fields = [
            "id",
            "title",
            "slug",
            "summary",
            "shape",
            "status",
            "visibility",
            "price_amount",
            "currency",
            "is_free",
            "effective_price",
            "sponsor",
            "published_at",
            "created_at",
        ]
        read_only_fields = fields


class OfferingDetailSerializer(serializers.ModelSerializer):
    """Serializer for offering detail view."""
    sponsor = SponsorSerializer(source="*", read_only=True)
    effective_price = serializers.IntegerField(read_only=True)
    asset_type = serializers.SerializerMethodField()
    asset_id = serializers.UUIDField(source="asset_object_id", read_only=True)

    class Meta:
        model = BazaarOffering
        fields = [
            "id",
            "title",
            "slug",
            "summary",
            "body",
            "shape",
            "status",
            "visibility",
            "price_amount",
            "currency",
            "is_free",
            "effective_price",
            "fulfillment_type",
            "fulfillment_config",
            "price_config",
            "asset_type",
            "asset_id",
            "sponsor",
            "published_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_asset_type(self, obj):
        if obj.asset_content_type:
            return obj.asset_content_type.model
        return None


class OfferingCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating offerings."""
    sponsor_type = serializers.CharField(write_only=True)
    sponsor_id = serializers.UUIDField(write_only=True)
    asset_type = serializers.CharField(write_only=True, required=False, allow_null=True)
    asset_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = BazaarOffering
        fields = [
            "title",
            "summary",
            "body",
            "shape",
            "visibility",
            "price_amount",
            "currency",
            "is_free",
            "fulfillment_type",
            "sponsor_type",
            "sponsor_id",
            "asset_type",
            "asset_id",
        ]

    def validate(self, attrs):
        from bazaar.services.validation import BazaarValidator, BazaarValidationError

        sponsor_type = attrs.pop("sponsor_type")
        sponsor_id = attrs.pop("sponsor_id")
        asset_type = attrs.pop("asset_type", None)
        asset_id = attrs.pop("asset_id", None)

        # Resolve sponsor
        try:
            ct = ContentType.objects.get(model=sponsor_type.lower())
            sponsor = ct.get_object_for_this_type(pk=sponsor_id)
        except (ContentType.DoesNotExist, Exception) as e:
            raise serializers.ValidationError({"sponsor_type": f"Invalid sponsor: {e}"})

        attrs["_sponsor"] = sponsor

        # Resolve asset if provided
        if asset_type and asset_id:
            try:
                asset_ct = ContentType.objects.get(model=asset_type.lower())
                asset = asset_ct.get_object_for_this_type(pk=asset_id)
                attrs["_asset"] = asset
            except (ContentType.DoesNotExist, Exception) as e:
                raise serializers.ValidationError({"asset_type": f"Invalid asset: {e}"})

        # Validate price
        try:
            BazaarValidator.validate_price(
                attrs.get("price_amount", 0),
                attrs.get("currency", "USD"),
                attrs.get("is_free", False),
            )
        except BazaarValidationError as e:
            raise serializers.ValidationError({"price_amount": e.message})

        return attrs

    def create(self, validated_data):
        from bazaar.services import OfferingService

        sponsor = validated_data.pop("_sponsor")
        asset = validated_data.pop("_asset", None)
        user = self.context["request"].user

        offering = OfferingService.create_offering(
            sponsor=sponsor,
            submitted_by=user,
            author=user,
            asset=asset,
            **validated_data,
        )

        return offering


class OfferingUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating offerings."""

    class Meta:
        model = BazaarOffering
        fields = [
            "title",
            "summary",
            "body",
            "visibility",
            "price_amount",
            "currency",
            "is_free",
            "fulfillment_config",
            "price_config",
        ]

    def update(self, instance, validated_data):
        from bazaar.services import OfferingService

        return OfferingService.update_offering(instance, **validated_data)


# =============================================================================
# Order Serializers
# =============================================================================

class OrderListSerializer(serializers.ModelSerializer):
    """Serializer for order list view."""
    offering_title = serializers.CharField(source="offering.title", read_only=True)
    offering_id = serializers.UUIDField(source="offering.id", read_only=True)
    buyer = BuyerSerializer(read_only=True)

    class Meta:
        model = BazaarOrder
        fields = [
            "id",
            "offering_id",
            "offering_title",
            "buyer",
            "amount",
            "currency",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class OrderDetailSerializer(serializers.ModelSerializer):
    """Serializer for order detail view."""
    offering = OfferingListSerializer(read_only=True)
    buyer = BuyerSerializer(read_only=True)
    vendor = serializers.SerializerMethodField()
    fulfillment_events = serializers.SerializerMethodField()

    class Meta:
        model = BazaarOrder
        fields = [
            "id",
            "offering",
            "buyer",
            "vendor",
            "amount",
            "currency",
            "status",
            "buyer_note",
            "vendor_note",
            "offering_snapshot",
            "stripe_payment_intent_id",
            "fulfillment_events",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_vendor(self, obj):
        if obj.offering and obj.offering.sponsor:
            return {
                "id": str(obj.offering.sponsor_object_id),
                "type": obj.offering.sponsor_content_type.model,
                "display_name": obj.offering.sponsor_display,
            }
        return None

    def get_fulfillment_events(self, obj):
        events = obj.fulfillment_events.all().order_by("-created_at")[:10]
        return FulfillmentEventSerializer(events, many=True).data


class OrderCreateSerializer(serializers.Serializer):
    """Serializer for creating orders."""
    offering_id = serializers.UUIDField()
    buyer_note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_offering_id(self, value):
        try:
            offering = BazaarOffering.objects.get(pk=value, deleted_at__isnull=True)
        except BazaarOffering.DoesNotExist:
            raise serializers.ValidationError("Offering not found.")

        self.context["offering"] = offering
        return value

    def create(self, validated_data):
        from bazaar.services import OrderService

        offering = self.context["offering"]
        buyer = self.context["request"].user

        order = OrderService.create_order(
            offering=offering,
            buyer=buyer,
            buyer_note=validated_data.get("buyer_note", ""),
        )

        return order


# =============================================================================
# Fulfillment Event Serializers
# =============================================================================

class FulfillmentEventSerializer(serializers.ModelSerializer):
    """Serializer for fulfillment events."""
    actor_username = serializers.CharField(source="actor_user.username", read_only=True, allow_null=True)

    class Meta:
        model = BazaarFulfillmentEvent
        fields = [
            "id",
            "event_type",
            "actor_type",
            "actor_username",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


# =============================================================================
# Action Serializers
# =============================================================================

class OfferingActionSerializer(serializers.Serializer):
    """Serializer for offering actions (publish, pause, etc.)."""
    action = serializers.ChoiceField(choices=["publish", "pause", "resume", "archive"])


class OrderActionSerializer(serializers.Serializer):
    """Serializer for order actions (confirm, fulfill, etc.)."""
    action = serializers.ChoiceField(choices=[
        "confirm", "start_fulfillment", "mark_delivered", "complete", "cancel"
    ])
    stripe_payment_intent_id = serializers.CharField(required=False, allow_blank=True)
    stripe_charge_id = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True)


# =============================================================================
# Stall Serializer (Virtual View)
# =============================================================================

class StallSerializer(serializers.Serializer):
    """Serializer for stall (vendor's public Bazaar surface)."""
    sponsor_id = serializers.UUIDField()
    sponsor_type = serializers.CharField()
    sponsor_display_name = serializers.CharField()
    offerings = OfferingListSerializer(many=True)
    offerings_count = serializers.IntegerField()
