# ai/utils/asset_creation.py

import logging


logger = logging.getLogger(__name__)

from inkwell.models import DeletedGutenbergInfo, SuggestedAsset, SuggestedGutenbergInfo
from inkwell.utils.fuzzy_blacklist import is_title_blacklisted


"""
    Create a SuggestedAsset if one doesn't already exist,
    and queue synopsis generation.
"""
def create_suggested_asset(data: dict) -> SuggestedAsset:

    logger.debug("create_suggested_asset - data: %s", data)

    title = data.get("title", "")
    author = data.get("author", "")

    if is_title_blacklisted(title, author):
        logger.info("⛔ Skipping blacklisted title: {title}")
        return None

    # 🚫 Skip if this gutenberg_id was previously deleted
    if data.get("source") == "gutenberg" and data.get("gutenberg_id"):
        if DeletedGutenbergInfo.objects.filter(gutenberg_id=data["gutenberg_id"]).exists():
            logger.info("🚫 Skipping deleted Gutenberg ID: {data['gutenberg_id']}")
            return None

    existing = SuggestedAsset.objects.filter(
        source_id=data.get("source_id"),
        source=data.get("source")
    ).first()

    if existing:
        logger.info("⏭️ Already exists: {existing.source_id} ({existing.title})")
        return existing

    # 🧹 Separate Gutenberg-only fields
    gutenberg_fields = {
        "gutenberg_id": data.pop("source_id", None),
        "text_url": data.pop("text_url", None),
        "version": data.pop("version", None),
    }

    asset = SuggestedAsset.objects.create(**data)
    logger.info(" Created suggested asset: %s", asset.title)

    # 🔗 If Gutenberg-specific, store source metadata
    if data.get("source") == "gutenberg" and gutenberg_fields["gutenberg_id"]:
        SuggestedGutenbergInfo.objects.create(
            asset=asset,
            **gutenberg_fields,
        )
        logger.info("📚 Linked Gutenberg ID: {gutenberg_fields['gutenberg_id']}")

    return asset
