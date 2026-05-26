from rest_framework import serializers


class CollectionListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    summary = serializers.CharField(allow_blank=True)
    slug = serializers.CharField()
    visibility = serializers.CharField()
    scope = serializers.CharField()

    sponsor_type = serializers.SerializerMethodField()
    sponsor_id = serializers.SerializerMethodField()
    sponsor_name = serializers.SerializerMethodField()

    item_count = serializers.SerializerMethodField()

    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_sponsor_type(self, obj):
        return obj.sponsor_content_type.model if obj.sponsor_content_type else 'unknown'

    def get_sponsor_id(self, obj):
        return str(obj.sponsor_object_id)

    def get_sponsor_name(self, obj):
        sponsor = obj.sponsor
        return getattr(sponsor, 'title', getattr(sponsor, 'display_name', str(sponsor)))

    def get_item_count(self, obj):
        return obj.items.count()


class CollectionDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    summary = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True)
    slug = serializers.CharField()
    visibility = serializers.CharField()
    scope = serializers.CharField()

    sponsor_type = serializers.SerializerMethodField()
    sponsor_id = serializers.SerializerMethodField()
    sponsor_name = serializers.SerializerMethodField()

    author_name = serializers.CharField(allow_blank=True)
    submitted_by = serializers.SerializerMethodField()

    item_count = serializers.SerializerMethodField()

    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_sponsor_type(self, obj):
        return obj.sponsor_content_type.model if obj.sponsor_content_type else 'unknown'

    def get_sponsor_id(self, obj):
        return str(obj.sponsor_object_id)

    def get_sponsor_name(self, obj):
        sponsor = obj.sponsor
        return getattr(sponsor, 'title', getattr(sponsor, 'display_name', str(sponsor)))

    def get_submitted_by(self, obj):
        if obj.submitted_by:
            return {
                'id': str(obj.submitted_by.id),
                'username': obj.submitted_by.username,
                'display_name': getattr(obj.submitted_by, 'display_name', obj.submitted_by.username),
            }
        return None

    def get_item_count(self, obj):
        return obj.items.count()


class CollectionItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField(allow_blank=True)
    order_index = serializers.IntegerField()
    folder_path = serializers.CharField(allow_blank=True)
    section_title = serializers.CharField(allow_blank=True)
    parent_id = serializers.SerializerMethodField()
    tags = serializers.JSONField()
    notes = serializers.CharField(allow_blank=True)
    is_folder = serializers.BooleanField()
    is_featured = serializers.BooleanField()
    is_hidden = serializers.BooleanField()

    content_type = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()

    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_parent_id(self, obj):
        return str(obj.parent_id) if obj.parent_id else None

    def _is_source_file_reference(self, obj):
        return not obj.is_folder and obj.content_type_id is None and bool(obj.content_object_id)

    def get_content_type(self, obj):
        if obj.is_folder:
            return 'folder'
        if self._is_source_file_reference(obj):
            return 'source_file'
        if not obj.content_type:
            return None
        model_name = obj.content_type.model
        if model_name == 'writingpiece':
            return 'writing_piece'
        if model_name == 'collection':
            return 'collection'
        # source_file and other types: return as-is (loose UUID reference to Stackroom)
        return model_name

    def get_content(self, obj):
        if obj.is_folder:
            return None

        if self._is_source_file_reference(obj):
            return {'id': str(obj.content_object_id)}

        if not obj.content_type:
            return None

        model_name = obj.content_type.model

        if model_name == 'writingpiece':
            content_obj = obj.content_object
            if not content_obj:
                return None
            return {
                'id': str(content_obj.id),
                'title': content_obj.title,
                'slug': content_obj.slug,
                'summary': getattr(content_obj, 'summary', ''),
                'writing_kind': getattr(content_obj, 'writing_kind', None),
                'status': getattr(content_obj, 'status', None),
                'author_name': getattr(content_obj, 'author_name', ''),
                'published_at': content_obj.published_at.isoformat() if getattr(content_obj, 'published_at', None) else None,
                'created_at': content_obj.created_at.isoformat(),
            }

        if model_name == 'collection':
            content_obj = obj.content_object
            if not content_obj:
                return None
            return {
                'id': str(content_obj.id),
                'title': content_obj.title,
                'slug': content_obj.slug,
                'summary': content_obj.summary,
                'item_count': content_obj.items.count(),
                'scope': content_obj.scope,
                'sponsor_type': content_obj.sponsor_content_type.model if content_obj.sponsor_content_type else 'unknown',
                'created_at': content_obj.created_at.isoformat(),
            }

        # source_file and other types: content lives in Stackroom; return UUID only
        return {'id': str(obj.content_object_id)}


class CollectionItemCreateSerializer(serializers.Serializer):
    content_type = serializers.ChoiceField(
        choices=['writing_piece', 'collection', 'source_file'],
    )
    content_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    order_index = serializers.IntegerField(required=False)
    folder_path = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    section_title = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    is_featured = serializers.BooleanField(required=False, default=False)


class CollectionItemUpdateSerializer(serializers.Serializer):
    order_index = serializers.IntegerField(required=False)
    folder_path = serializers.CharField(max_length=500, required=False, allow_blank=True)
    section_title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    is_featured = serializers.BooleanField(required=False)
    is_hidden = serializers.BooleanField(required=False)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)


class CollectionItemBulkReorderSerializer(serializers.Serializer):
    items = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()),
    )

    def validate_items(self, value):
        for item in value:
            if 'id' not in item or 'order_index' not in item:
                raise serializers.ValidationError("Each item must have 'id' and 'order_index'")
        return value


class CollectionCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=100, required=True)
    summary = serializers.CharField(required=False, allow_blank=True, default='')
    body = serializers.CharField(required=False, allow_blank=True, default='')
    sponsor_type = serializers.ChoiceField(choices=['group', 'user'], required=True)
    sponsor_id = serializers.UUIDField(required=True)
    author_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    visibility = serializers.ChoiceField(
        choices=['public', 'members', 'unlisted', 'private'],
        required=False,
        default='private',
    )
    scope = serializers.ChoiceField(
        choices=['writing', 'audio', 'course', 'general'],
        required=False,
        default='general',
    )


class CollectionUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=100, required=False)
    summary = serializers.CharField(required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    author_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(
        choices=['public', 'members', 'unlisted', 'private'],
        required=False,
    )
    scope = serializers.ChoiceField(
        choices=['writing', 'audio', 'course', 'general'],
        required=False,
    )


class WritingPieceMinimalSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    slug = serializers.CharField()
    summary = serializers.CharField(allow_blank=True)
    writing_kind = serializers.CharField()
    status = serializers.CharField()
    author_name = serializers.CharField(allow_blank=True)
    published_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    in_collection = serializers.BooleanField(default=False)
    item_count = serializers.IntegerField(default=0)
