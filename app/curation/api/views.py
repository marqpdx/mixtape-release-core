from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from curation.models import Collection, CollectionItem
from curation.api.serializers import (
    CollectionCreateSerializer,
    CollectionDetailSerializer,
    CollectionItemBulkReorderSerializer,
    CollectionItemCreateSerializer,
    CollectionItemSerializer,
    CollectionItemUpdateSerializer,
    CollectionListSerializer,
    CollectionUpdateSerializer,
    WritingPieceMinimalSerializer,
)


# ============================================================================
# Access Control
# ============================================================================

def _get_group_membership(user, group_id):
    from django.contrib.auth import get_user_model
    from groups.models import GroupMembership
    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)
    return GroupMembership.objects.filter(
        group_id=group_id,
        member_content_type=user_ct,
        member_object_id=user.id,
        is_active=True,
        is_pending=False,
    ).first()


def _has_write_role(membership):
    if not membership:
        return False
    return bool({'owner', 'admin', 'steward'}.intersection(set(membership.roles or [])))


def _has_admin_role(membership):
    if not membership:
        return False
    return bool({'owner', 'admin'}.intersection(set(membership.roles or [])))


def _check_read(user, collection):
    if user.is_staff or user.is_superuser:
        return
    from django.contrib.auth import get_user_model
    from groups.models import Group
    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)
    group_ct = ContentType.objects.get_for_model(Group)

    if collection.sponsor_content_type == user_ct:
        if str(collection.sponsor_object_id) != str(user.id):
            raise Http404
        return

    if collection.sponsor_content_type == group_ct:
        if collection.visibility in ('public', 'unlisted'):
            return
        membership = _get_group_membership(user, collection.sponsor_object_id)
        if collection.visibility == 'members':
            if not membership:
                raise Http404
        elif collection.visibility == 'private':
            if not _has_admin_role(membership):
                raise Http404
        return

    raise Http404


def _check_write(user, collection):
    if user.is_staff or user.is_superuser:
        return
    from django.contrib.auth import get_user_model
    from groups.models import Group
    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)
    group_ct = ContentType.objects.get_for_model(Group)

    if collection.sponsor_content_type == user_ct:
        if str(collection.sponsor_object_id) != str(user.id):
            raise Http404
        return

    if collection.sponsor_content_type == group_ct:
        membership = _get_group_membership(user, collection.sponsor_object_id)
        if collection.visibility == 'private':
            if not _has_admin_role(membership):
                raise Http404
        else:
            if not _has_write_role(membership):
                raise Http404
        return

    raise Http404


def _check_admin(user, collection):
    if user.is_staff or user.is_superuser:
        return
    from django.contrib.auth import get_user_model
    from groups.models import Group
    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)
    group_ct = ContentType.objects.get_for_model(Group)

    if collection.sponsor_content_type == user_ct:
        if str(collection.sponsor_object_id) != str(user.id):
            raise Http404
        return

    if collection.sponsor_content_type == group_ct:
        membership = _get_group_membership(user, collection.sponsor_object_id)
        if not _has_admin_role(membership):
            raise Http404
        return

    raise Http404


def _filter_visible(user, qs):
    from django.db.models import Q
    from django.contrib.auth import get_user_model
    from groups.models import Group, GroupMembership
    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)
    group_ct = ContentType.objects.get_for_model(Group)

    if user.is_staff or user.is_superuser:
        return qs

    user_q = Q(sponsor_content_type=user_ct, sponsor_object_id=user.id)
    public_q = Q(sponsor_content_type=group_ct, visibility='public')

    member_group_ids = GroupMembership.objects.filter(
        member_content_type=user_ct,
        member_object_id=user.id,
        is_active=True,
        is_pending=False,
    ).values_list('group_id', flat=True)
    members_q = Q(sponsor_content_type=group_ct, visibility='members', sponsor_object_id__in=member_group_ids)

    admin_group_ids = GroupMembership.objects.filter(
        member_content_type=user_ct,
        member_object_id=user.id,
        is_active=True,
        is_pending=False,
        roles__overlap=['owner', 'admin'],
    ).values_list('group_id', flat=True)
    private_q = Q(sponsor_content_type=group_ct, visibility='private', sponsor_object_id__in=admin_group_ids)

    # unlisted excluded from lists (accessible via direct link only)
    return qs.filter(user_q | public_q | members_q | private_q)


# ============================================================================
# Views
# ============================================================================

class CollectionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Collection.objects.all().order_by('-created_at')

        sponsor_type = request.query_params.get('sponsor_type')
        if sponsor_type == 'group':
            from groups.models import Group
            ct = ContentType.objects.get_for_model(Group)
            qs = qs.filter(sponsor_content_type=ct)
        elif sponsor_type == 'user':
            from django.contrib.auth import get_user_model
            ct = ContentType.objects.get_for_model(get_user_model())
            qs = qs.filter(sponsor_content_type=ct)

        sponsor_id = request.query_params.get('sponsor_id')
        if sponsor_id:
            qs = qs.filter(sponsor_object_id=sponsor_id)

        qs = _filter_visible(request.user, qs)
        serializer = CollectionListSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = CollectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data['sponsor_type'] == 'group':
            from groups.models import Group
            sponsor_ct = ContentType.objects.get_for_model(Group)
            sponsor_obj = get_object_or_404(Group, id=data['sponsor_id'])
        else:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            sponsor_ct = ContentType.objects.get_for_model(User)
            sponsor_obj = get_object_or_404(User, id=data['sponsor_id'])

        _check_admin(request.user, Collection(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=data['sponsor_id'],
        ))

        collection = Collection.objects.create(
            title=data['title'],
            summary=data.get('summary', ''),
            body=data.get('body', ''),
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=data['sponsor_id'],
            author_name=data.get('author_name', ''),
            visibility=data.get('visibility', 'private'),
            scope=data.get('scope', 'general'),
            submitted_by=request.user,
        )

        return Response(CollectionDetailSerializer(collection).data, status=drf_status.HTTP_201_CREATED)


class CollectionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id):
        collection = get_object_or_404(Collection, id=collection_id)
        _check_read(request.user, collection)
        return Response(CollectionDetailSerializer(collection).data)

    def patch(self, request, collection_id):
        collection = get_object_or_404(Collection, id=collection_id)
        _check_admin(request.user, collection)

        serializer = CollectionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        for field in ('title', 'summary', 'body', 'author_name', 'visibility', 'scope'):
            if field in data:
                setattr(collection, field, data[field])
        collection.save()

        return Response(CollectionDetailSerializer(collection).data)

    def delete(self, request, collection_id):
        collection = get_object_or_404(Collection, id=collection_id)
        _check_admin(request.user, collection)

        collection.delete()
        return Response(status=drf_status.HTTP_204_NO_CONTENT)


class CollectionAvailableFilesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id):
        from inkwell.stackroom_http_client import get_library_source_files, StackroomClientError
        from django.contrib.contenttypes.models import ContentType

        collection = get_object_or_404(Collection, id=collection_id)
        _check_read(request.user, collection)

        # Resolve sponsor → stackroom_library_id
        sponsor_ct = collection.sponsor_content_type
        sponsor_id = collection.sponsor_object_id
        sponsor_model = sponsor_ct.model_class()
        try:
            sponsor = sponsor_model.objects.get(pk=sponsor_id)
        except sponsor_model.DoesNotExist:
            return Response({"files": []})

        library_id = getattr(sponsor, "stackroom_library_id", None)
        if not library_id:
            return Response({"files": []})

        try:
            raw_files = get_library_source_files(library_id)
        except StackroomClientError:
            return Response({"files": []})

        # Count how many times each source_file UUID appears in this collection
        from collections import Counter
        existing_counts = Counter(
            str(item.content_object_id)
            for item in collection.items.filter(content_type__isnull=True)
        )

        files_data = []
        for f in raw_files:
            file_id = f["id"]
            count = existing_counts.get(file_id, 0)
            files_data.append({
                "id": file_id,
                "filename": f["filename"],
                "content_type": f["content_type"],
                "size_bytes": f["size_bytes"],
                "origin": f["origin"],
                "created_at": f["created_at"],
                "in_collection": count > 0,
                "item_count": count,
            })

        return Response(files_data)


class CollectionAvailableDocumentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id):
        collection = get_object_or_404(Collection, id=collection_id)
        _check_read(request.user, collection)

        from writing.models import WritingPiece
        from dispatch.models import Post

        writing_pieces = WritingPiece.objects.filter(
            status='published',
            sponsor_content_type=collection.sponsor_content_type,
            sponsor_object_id=collection.sponsor_object_id,
        ).order_by('-published_at')

        posts = Post.objects.filter(
            published_at__isnull=False,
            deleted_at__isnull=True,
            sponsor_content_type=collection.sponsor_content_type,
            sponsor_object_id=collection.sponsor_object_id,
        ).order_by('-published_at')

        wp_ct = ContentType.objects.get_for_model(WritingPiece)
        post_ct = ContentType.objects.get_for_model(Post)

        docs_data = []
        for wp in writing_pieces:
            item_count = collection.items.filter(
                content_type=wp_ct,
                content_object_id=wp.id,
            ).count()
            docs_data.append({
                'id': wp.id,
                'title': wp.title,
                'slug': getattr(wp, 'slug', ''),
                'summary': getattr(wp, 'summary', ''),
                'writing_kind': wp.writing_kind,
                'status': wp.status,
                'doc_type': 'writing_piece',
                'author_name': wp.author_name,
                'published_at': wp.published_at,
                'created_at': wp.created_at,
                'in_collection': item_count > 0,
                'item_count': item_count,
            })

        for post in posts:
            item_count = collection.items.filter(
                content_type=post_ct,
                content_object_id=post.id,
            ).count()
            docs_data.append({
                'id': post.id,
                'title': post.title or '(untitled dispatch)',
                'slug': getattr(post, 'slug', ''),
                'summary': getattr(post, 'summary', ''),
                'writing_kind': 'dispatch',
                'status': 'published',
                'doc_type': 'dispatch_post',
                'author_name': getattr(post, 'author_display', ''),
                'published_at': post.published_at,
                'created_at': post.created_at,
                'in_collection': item_count > 0,
                'item_count': item_count,
            })

        docs_data.sort(key=lambda d: d['published_at'] or d['created_at'], reverse=True)
        return Response(WritingPieceMinimalSerializer(docs_data, many=True).data)


class CollectionItemListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id):
        collection = get_object_or_404(Collection, id=collection_id)
        _check_read(request.user, collection)

        items = collection.items.select_related('content_type').all()

        folder = request.query_params.get('folder')
        if folder:
            items = items.filter(folder_path=folder)

        if request.query_params.get('featured') == 'true':
            items = items.filter(is_featured=True)

        if request.query_params.get('hidden') != 'true':
            items = items.filter(is_hidden=False)

        return Response(CollectionItemSerializer(items, many=True).data)

    def post(self, request, collection_id):
        collection = get_object_or_404(Collection, id=collection_id)
        _check_write(request.user, collection)

        serializer = CollectionItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        content_type_label = data['content_type']

        if content_type_label == 'writing_piece':
            from writing.models import WritingPiece
            content_obj = get_object_or_404(WritingPiece, id=data['content_id'])
            if content_obj.status != 'published':
                return Response(
                    {'detail': 'Only published WritingPieces can be added to Collections'},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            if (content_obj.sponsor_content_type != collection.sponsor_content_type or
                    content_obj.sponsor_object_id != collection.sponsor_object_id):
                return Response(
                    {'detail': 'WritingPiece sponsor must match Collection sponsor'},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            content_model = WritingPiece

        elif content_type_label == 'dispatch_post':
            from dispatch.models import Post
            content_obj = get_object_or_404(Post, id=data['content_id'])
            if not content_obj.published_at:
                return Response(
                    {'detail': 'Only published Dispatch posts can be added to Collections'},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            if (content_obj.sponsor_content_type != collection.sponsor_content_type or
                    content_obj.sponsor_object_id != collection.sponsor_object_id):
                return Response(
                    {'detail': 'Dispatch post sponsor must match Collection sponsor'},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            content_model = Post

        elif content_type_label == 'collection':
            content_obj = get_object_or_404(Collection, id=data['content_id'])
            if content_obj.id == collection.id:
                return Response(
                    {'detail': 'Collection cannot link to itself'},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            if (content_obj.sponsor_content_type != collection.sponsor_content_type or
                    content_obj.sponsor_object_id != collection.sponsor_object_id):
                return Response(
                    {'detail': 'Linked Collection must have same sponsor'},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            content_model = Collection

        elif content_type_label == 'source_file':
            # SourceFile lives in Stackroom service — stored as a loose UUID reference.
            # No Django-side validation possible; trust the caller.
            content_type = None
            content_obj = None
            content_model = None
        else:
            return Response(
                {'detail': "Invalid content_type. Must be 'writing_piece', 'dispatch_post', 'collection', or 'source_file'"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        if content_model is not None:
            content_type = ContentType.objects.get_for_model(content_model)

        if 'order_index' not in data:
            max_index = collection.items.aggregate(max_idx=models.Max('order_index'))['max_idx']
            data['order_index'] = (max_index or 0) + 1

        title = data.get('title', '')
        if not title and content_obj is not None:
            title = getattr(content_obj, 'filename', None) or getattr(content_obj, 'title', '')

        item = CollectionItem.objects.create(
            collection=collection,
            title=title,
            content_type=content_type,
            content_object_id=data['content_id'],
            order_index=data['order_index'],
            folder_path=data.get('folder_path', ''),
            section_title=data.get('section_title', ''),
            tags=data.get('tags', []),
            notes=data.get('notes', ''),
            is_featured=data.get('is_featured', False),
        )

        return Response(CollectionItemSerializer(item).data, status=drf_status.HTTP_201_CREATED)


class CollectionItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id, item_id):
        collection = get_object_or_404(Collection, id=collection_id)
        item = get_object_or_404(CollectionItem, id=item_id, collection=collection)
        _check_read(request.user, collection)
        return Response(CollectionItemSerializer(item).data)

    def patch(self, request, collection_id, item_id):
        collection = get_object_or_404(Collection, id=collection_id)
        item = get_object_or_404(CollectionItem, id=item_id, collection=collection)
        _check_write(request.user, collection)

        serializer = CollectionItemUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        for field in ('order_index', 'folder_path', 'section_title', 'tags', 'notes',
                      'is_featured', 'is_hidden', 'title'):
            if field in data:
                setattr(item, field, data[field])
        item.save()

        return Response(CollectionItemSerializer(item).data)

    def delete(self, request, collection_id, item_id):
        collection = get_object_or_404(Collection, id=collection_id)
        item = get_object_or_404(CollectionItem, id=item_id, collection=collection)
        _check_write(request.user, collection)
        item.delete()
        return Response(status=drf_status.HTTP_204_NO_CONTENT)


class CollectionItemReorderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, collection_id):
        collection = get_object_or_404(Collection, id=collection_id)
        _check_write(request.user, collection)

        serializer = CollectionItemBulkReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items_data = serializer.validated_data['items']

        item_ids = [item['id'] for item in items_data]
        items_qs = CollectionItem.objects.filter(id__in=item_ids, collection=collection)
        if items_qs.count() != len(item_ids):
            return Response(
                {'detail': 'Some items do not belong to this Collection'},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            for item_data in items_data:
                item = CollectionItem.objects.get(id=item_data['id'], collection=collection)
                item.order_index = int(item_data['order_index'])

                if 'parent_id' in item_data:
                    parent_id = item_data['parent_id']
                    if not parent_id or parent_id in ('null', ''):
                        item.parent = None
                    else:
                        parent = get_object_or_404(CollectionItem, id=parent_id, collection=collection)
                        if not parent.is_folder:
                            return Response(
                                {'detail': f'Cannot nest under non-folder item {parent_id}'},
                                status=drf_status.HTTP_400_BAD_REQUEST,
                            )
                        item.parent = parent

                item.save(update_fields=['order_index', 'parent', 'updated_at'])

        return Response({'detail': f'Updated {len(items_data)} items'})


class CollectionItemCopyFromView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, collection_id, source_collection_id):
        collection = get_object_or_404(Collection, id=collection_id)
        source = get_object_or_404(Collection, id=source_collection_id)
        _check_write(request.user, collection)
        _check_read(request.user, source)

        max_index = collection.items.aggregate(max_idx=models.Max('order_index'))['max_idx'] or 0

        copied = 0
        with transaction.atomic():
            for item in source.items.filter(is_folder=False).order_by('order_index'):
                max_index += 1
                CollectionItem.objects.create(
                    collection=collection,
                    title=item.title,
                    content_type=item.content_type,
                    content_object_id=item.content_object_id,
                    order_index=max_index,
                    folder_path=item.folder_path,
                    tags=item.tags,
                    notes=item.notes,
                    is_featured=item.is_featured,
                )
                copied += 1

        return Response({'detail': f'Copied {copied} items'})
