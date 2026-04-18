from classifications.models import Category, Tag


class TagSerializer:
    """Plain dict helper — not a DRF ModelSerializer, keeps views clean."""

    @staticmethod
    def from_usage(usage) -> dict:
        tag = usage.classification
        return {
            "usage_id": str(usage.id),
            "id": tag.id,
            "title": tag.title,
            "slug": tag.slug,
        }

    @staticmethod
    def from_tag(tag) -> dict:
        return {"id": tag.id, "title": tag.title, "slug": tag.slug}


class CategorySerializer:
    @staticmethod
    def from_usage(usage) -> dict:
        cat = usage.classification
        return {
            "usage_id": str(usage.id),
            "id": cat.id,
            "title": cat.title,
            "slug": cat.slug,
        }

    @staticmethod
    def from_category(cat) -> dict:
        return {"id": cat.id, "title": cat.title, "slug": cat.slug}
