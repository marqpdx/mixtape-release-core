"""Public, placement-aware aggregation for writing catalog surfaces."""

from collections import Counter, defaultdict

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from classifications.models import Category, ClassificationUsage, Tag
from curation.models import Collection, CollectionItem
from groups.models.group import Group
from publishing.models import ContentPlacement
from publishing.services.content_access import can_view_placement
from publishing.services.content_display import get_display_payload
from writing.models import WritingPiece
from writing.synopsis_service import _extract_plain_text

PUBLIC_BROWSE_CHANNELS = ("feed", "shelf")


def browse_placements(piece_ids, *, viewer=None, allowed_visibilities=("public",)):
    """Return the newest viewable browse placement for each writing piece."""
    if not piece_ids:
        return {}, defaultdict(list)

    piece_ct = ContentType.objects.get_for_model(WritingPiece)
    placements = (
        ContentPlacement.objects.filter(
            source_content_type=piece_ct,
            source_object_id__in=piece_ids,
            channel__in=PUBLIC_BROWSE_CHANNELS,
            visibility__in=allowed_visibilities,
        )
        .select_related("target_content_type")
        .order_by("-created_at")
    )

    selected = {}
    all_by_piece = defaultdict(list)
    for placement in placements:
        if not can_view_placement(placement, viewer):
            continue
        piece_id = str(placement.source_object_id)
        selected.setdefault(piece_id, placement)
        all_by_piece[piece_id].append(placement)
    return selected, all_by_piece


def _sponsor_key(content_type_id, object_id, *, user_ct_id, group_ct_id, users, groups):
    if content_type_id == user_ct_id:
        sponsor = users.get(object_id)
        return f"user:{sponsor.username}" if sponsor else None
    if content_type_id == group_ct_id:
        sponsor = groups.get(object_id)
        return f"group:{sponsor.slug}" if sponsor else None
    return None


def _sponsor_payload(key, *, users_by_username, groups_by_slug):
    if not key:
        return None
    kind, slug = key.split(":", 1)
    if kind == "user":
        user = users_by_username.get(slug)
        profile = getattr(user, "profile", None) if user else None
        return {
            "type": "user",
            "slug": slug,
            "title": profile.display_name if profile and profile.display_name else slug,
        }
    group = groups_by_slug.get(slug)
    if not group:
        return None
    return {"type": "group", "slug": group.slug, "title": group.title}


def _taxonomy_for_pieces(piece_ids, *, owner, groups, placements_by_piece):
    piece_ct = ContentType.objects.get_for_model(WritingPiece)
    user_ct = ContentType.objects.get_for_model(get_user_model())
    group_ct = ContentType.objects.get_for_model(Group)
    category_ct = ContentType.objects.get_for_model(Category)
    tag_ct = ContentType.objects.get_for_model(Tag)
    collection_ct = ContentType.objects.get_for_model(Collection)

    allowed_user_ids = {owner.id}
    allowed_group_ids = {group.id for group in groups}
    users = {owner.id: owner}
    groups_by_id = {group.id: group for group in groups}
    users_by_username = {owner.username: owner}
    groups_by_slug = {group.slug: group for group in groups}

    usages = ClassificationUsage.objects.filter(
        classification_client_content_type=piece_ct,
        classification_client_object_id__in=[str(piece_id) for piece_id in piece_ids],
        classification_content_type__in=[category_ct, tag_ct],
    )

    category_ids = set()
    tag_ids = set()
    usage_rows = []
    for usage in usages:
        usage_rows.append(usage)
        if usage.classification_content_type_id == category_ct.id:
            category_ids.add(usage.classification_object_id)
        else:
            tag_ids.add(usage.classification_object_id)

    categories = {
        category.id: category
        for category in Category.objects.filter(id__in=category_ids).filter(
            Q(sponsor_content_type=user_ct, sponsor_object_id__in=allowed_user_ids)
            | Q(sponsor_content_type=group_ct, sponsor_object_id__in=allowed_group_ids)
        )
    }
    tags = {tag.id: tag for tag in Tag.objects.filter(id__in=tag_ids)}

    categories_by_piece = defaultdict(list)
    tags_by_piece = defaultdict(list)
    category_counts = Counter()
    tag_counts = Counter()

    for usage in usage_rows:
        piece_id = usage.classification_client_object_id
        if usage.classification_content_type_id == category_ct.id:
            category = categories.get(usage.classification_object_id)
            if not category:
                continue
            sponsor_key = _sponsor_key(
                category.sponsor_content_type_id,
                category.sponsor_object_id,
                user_ct_id=user_ct.id,
                group_ct_id=group_ct.id,
                users=users,
                groups=groups_by_id,
            )
            if not sponsor_key:
                continue
            key = f"{sponsor_key}:category:{category.slug}"
            item = {
                "key": key,
                "slug": category.slug,
                "title": category.title,
                "summary": category.summary,
                "color": category.color,
                "sponsor": _sponsor_payload(
                    sponsor_key,
                    users_by_username=users_by_username,
                    groups_by_slug=groups_by_slug,
                ),
            }
            categories_by_piece[piece_id].append(item)
            category_counts[key] += 1
        else:
            tag = tags.get(usage.classification_object_id)
            if not tag:
                continue
            item = {"slug": tag.slug, "title": tag.title, "color": tag.color}
            tags_by_piece[piece_id].append(item)
            tag_counts[tag.slug] += 1

    collections = {
        collection.id: collection
        for collection in Collection.objects.filter(
            visibility="public",
            scope="writing",
        ).filter(
            Q(sponsor_content_type=user_ct, sponsor_object_id__in=allowed_user_ids)
            | Q(sponsor_content_type=group_ct, sponsor_object_id__in=allowed_group_ids)
        )
    }
    collections_by_piece = defaultdict(list)
    collection_counts = Counter()

    collection_piece_pairs = set()
    for item in CollectionItem.objects.filter(
        collection_id__in=collections,
        content_type=piece_ct,
        content_object_id__in=piece_ids,
        is_folder=False,
        is_hidden=False,
    ):
        collection_piece_pairs.add((str(item.content_object_id), item.collection_id))

    for piece_id, placements in placements_by_piece.items():
        for placement in placements:
            if placement.target_content_type_id == collection_ct.id:
                collection_piece_pairs.add((piece_id, placement.target_object_id))

    for piece_id, collection_id in collection_piece_pairs:
        collection = collections.get(collection_id)
        if not collection:
            continue
        sponsor_key = _sponsor_key(
            collection.sponsor_content_type_id,
            collection.sponsor_object_id,
            user_ct_id=user_ct.id,
            group_ct_id=group_ct.id,
            users=users,
            groups=groups_by_id,
        )
        if not sponsor_key:
            continue
        key = f"{sponsor_key}:collection:{collection.slug}"
        item = {
            "key": key,
            "slug": collection.slug,
            "title": collection.title,
            "summary": collection.summary,
            "sponsor": _sponsor_payload(
                sponsor_key,
                users_by_username=users_by_username,
                groups_by_slug=groups_by_slug,
            ),
        }
        collections_by_piece[piece_id].append(item)
        collection_counts[key] += 1

    category_facets = {}
    for items in categories_by_piece.values():
        for item in items:
            category_facets[item["key"]] = {
                **item,
                "count": category_counts[item["key"]],
            }
    collection_facets = {}
    for items in collections_by_piece.values():
        for item in items:
            collection_facets[item["key"]] = {
                **item,
                "count": collection_counts[item["key"]],
            }
    tag_facets = {
        tag.slug: {
            "slug": tag.slug,
            "title": tag.title,
            "color": tag.color,
            "count": tag_counts[tag.slug],
        }
        for tag in tags.values()
        if tag_counts[tag.slug]
    }

    return {
        "categories_by_piece": categories_by_piece,
        "collections_by_piece": collections_by_piece,
        "tags_by_piece": tags_by_piece,
        "categories": sorted(
            category_facets.values(), key=lambda item: item["title"].lower()
        ),
        "collections": sorted(
            collection_facets.values(), key=lambda item: item["title"].lower()
        ),
        "tags": sorted(tag_facets.values(), key=lambda item: item["title"].lower()),
    }


def build_public_site_writing_catalog(*, owner, groups):
    """Build the complete public catalog before request-level filtering/pagination."""
    group_ct = ContentType.objects.get_for_model(Group)
    candidates = list(
        WritingPiece.objects.filter(status="published")
        .filter(
            Q(author=owner)
            | Q(
                sponsor_content_type=group_ct,
                sponsor_object_id__in=[group.id for group in groups],
            )
        )
        .select_related("author", "author__profile", "sponsor_content_type")
        .order_by("-published_at", "-created_at")
        .distinct()
    )
    placements, placements_by_piece = browse_placements(
        [piece.id for piece in candidates]
    )
    resolved_pieces = []
    for piece in candidates:
        placement = placements.get(str(piece.id))
        if not placement:
            continue
        try:
            payload = get_display_payload(placement)
        except Exception:
            continue
        resolved_pieces.append((piece, payload))

    taxonomy = _taxonomy_for_pieces(
        [piece.id for piece, _payload in resolved_pieces],
        owner=owner,
        groups=groups,
        placements_by_piece=placements_by_piece,
    )

    groups_by_id = {group.id: group for group in groups}
    items = []
    archive_counts = Counter()
    for piece, payload in resolved_pieces:
        piece_id = str(piece.id)
        metadata = payload.get("metadata") or {}
        body_json = metadata.get("body_json") or piece.body_json or {}
        profile = getattr(piece.author, "profile", None) if piece.author else None
        sponsor_group = None
        if piece.sponsor_content_type_id == group_ct.id:
            group = groups_by_id.get(piece.sponsor_object_id)
            if group:
                sponsor_group = {"slug": group.slug, "title": group.title}

        source_keys = []
        if piece.author_id == owner.id:
            source_keys.append(f"user:{owner.username}")
        if sponsor_group:
            source_keys.append(f"group:{sponsor_group['slug']}")

        categories = taxonomy["categories_by_piece"].get(piece_id, [])
        collections = taxonomy["collections_by_piece"].get(piece_id, [])
        tags = taxonomy["tags_by_piece"].get(piece_id, [])
        if piece.published_at:
            archive_counts[piece.published_at.year] += 1

        items.append(
            {
                "id": piece_id,
                "slug": piece.slug,
                "title": metadata.get("title") or piece.title,
                "excerpt": metadata.get("excerpt") or piece.excerpt or "",
                "body_preview": _extract_plain_text(body_json, char_limit=400)
                or piece.excerpt
                or "",
                "cover_image": metadata.get("cover_image") or "",
                "writing_kind": piece.writing_kind,
                "published_at": piece.published_at,
                "reading_time": piece.reading_time,
                "author": {
                    "username": piece.author.username if piece.author else "",
                    "display_name": (
                        profile.display_name
                        if profile and profile.display_name
                        else (
                            piece.author.username if piece.author else piece.author_name
                        )
                    ),
                    "avatar_url": profile.avatar_url if profile else "",
                },
                "sponsor_group": sponsor_group,
                "source_keys": source_keys,
                "categories": categories,
                "collections": collections,
                "tags": tags,
            }
        )

    taxonomy["archives"] = [
        {"year": year, "count": count}
        for year, count in sorted(archive_counts.items(), reverse=True)
    ]
    return items, taxonomy
