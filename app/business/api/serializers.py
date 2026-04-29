from rest_framework import serializers

from business.models import FixItem, Supplier, SupplyRequest


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact_info", "notes", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class SupplyRequestSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)

    class Meta:
        model = SupplyRequest
        fields = [
            "id",
            "item_name",
            "quantity_note",
            "supplier",
            "supplier_name",
            "status",
            "raw_input",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "supplier_name", "created_at", "updated_at"]


class FixItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FixItem
        fields = [
            "id",
            "title",
            "description",
            "status",
            "raw_input",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
