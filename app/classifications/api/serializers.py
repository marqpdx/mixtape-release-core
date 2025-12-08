# classifications/api/serializers.py

from rest_framework import serializers

from ..models import Tag, Category, ClassificationUsage


class TagSerializer(serializers.ModelSerializer):
    """Serializer for Tag model"""
    usage_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Tag
        fields = ['id', 'title', 'slug', 'summary', 'color', 'usage_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'slug', 'usage_count', 'created_at', 'updated_at']


class CategorySerializer(serializers.ModelSerializer):
    """Serializer for Category model"""
    usage_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'title', 'slug', 'summary', 'color', 'usage_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'slug', 'usage_count', 'created_at', 'updated_at']


class ClassificationUsageSerializer(serializers.ModelSerializer):
    """Serializer for ClassificationUsage through model"""

    class Meta:
        model = ClassificationUsage
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]
