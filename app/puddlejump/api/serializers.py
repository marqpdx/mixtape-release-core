from rest_framework import serializers

from ..models import Library, LibraryItem


class LibraryItemSerializer(serializers.ModelSerializer):
    content_type = serializers.CharField(source='content_type_str', read_only=True)

    class Meta:
        model = LibraryItem
        fields = [
            'id', 'is_folder', 'title', 'folder_path', 'tags', 'notes',
            'is_featured', 'order_index', 'content_type', 'content_id',
            'filename', 'size_bytes', 'hash_sha256', 's3_key',
            'source_file_id', 'latest_version_id',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PersonalPuddlejumpSerializer(serializers.ModelSerializer):
    items = LibraryItemSerializer(many=True, read_only=True)
    file_count = serializers.IntegerField(read_only=True)
    total_size_bytes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Library
        fields = [
            'id', 'title', 'slug', 'summary', 'body',
            'file_count', 'total_size_bytes', 'last_synced_at',
            'items', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'file_count', 'total_size_bytes', 'created_at', 'updated_at']
