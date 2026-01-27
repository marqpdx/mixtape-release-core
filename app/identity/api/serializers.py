# apps/identity/api/serializers.py

from rest_framework import serializers
import re

from identity.models import EmblemAvatar, EmblemAvatarType
from utils.storage.storage_utils import key_to_url

HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")

class EmblemAvatarTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmblemAvatarType
        fields = (
            "id", "engine", "style", "label",
            "is_upload", "is_generator",
            "supports_fg", "supports_bg", "supports_initials",
        )

class EmblemAvatarSerializer(serializers.ModelSerializer):
    type = serializers.PrimaryKeyRelatedField(queryset=EmblemAvatarType.objects.all())

    size_48_url  = serializers.SerializerMethodField()
    size_96_url  = serializers.SerializerMethodField()
    size_192_url = serializers.SerializerMethodField()
    size_512_url = serializers.SerializerMethodField()
    og_1200x630_url = serializers.SerializerMethodField()


    class Meta:
        model = EmblemAvatar
        fields = (
            "id", "type", "image_path",
            "seed", "style_variant", "fg", "bg", "initials", "palette",
            # stored keys
            "size_48", "size_96", "size_192", "size_512", "og_1200x630",
            # derived urls
            "size_48_url", "size_96_url", "size_192_url", "size_512_url", "og_1200x630_url",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "size_48","size_96","size_192","size_512","og_1200x630",
            "size_48_url","size_96_url","size_192_url","size_512_url","og_1200x630_url",
            "created_at","updated_at",
        )

    def _url(self, key: str | None) -> str | None:
        return key_to_url(key)


    def get_size_48_url(self, obj):   return self._url(obj.size_48)
    def get_size_96_url(self, obj):   return self._url(obj.size_96)
    def get_size_192_url(self, obj):  return self._url(obj.size_192)
    def get_size_512_url(self, obj):  return self._url(obj.size_512)
    def get_og_1200x630_url(self, obj): return self._url(obj.og_1200x630)


    def validate(self, attrs):
        t = attrs.get("type") or (self.instance and self.instance.type)
        if not t:
            return attrs

        # Upload invariants
        if t.engine == "upload":
            image_path = attrs.get("image_path") or (self.instance and self.instance.image_path)
            if not image_path:
                raise serializers.ValidationError("image_path is required for uploads.")
        else:
            # Generator invariants
            if not t.is_generator:
                raise serializers.ValidationError("Selected type must be a generator.")
            seed = attrs.get("seed") or (self.instance and self.instance.seed)
            if not seed:
                raise serializers.ValidationError("seed is required for generator types.")

        # Colors
        for key in ("fg", "bg"):
            v = attrs.get(key)
            if v:
                if not HEX_RE.match(v):
                    raise serializers.ValidationError({key: "Use #RRGGBB"})
                if not v.startswith("#"):
                    attrs[key] = f"#{v}"
        # Palette (JSONField list of hex strings)
        pal = attrs.get("palette", None)
        if pal is not None:
            if not isinstance(pal, list):
                raise serializers.ValidationError({"palette": "Must be a list of hex colors."})
            bad = [c for c in pal if not isinstance(c, str) or not HEX_RE.match(c)]
            if bad:
                raise serializers.ValidationError({"palette": f"Invalid hex colors: {bad}"})
            attrs["palette"] = [c if c.startswith("#") else f"#{c}" for c in pal]

        return attrs



class EmblemAvatarListSerializer(serializers.ModelSerializer):
    size_48_url  = serializers.SerializerMethodField()
    size_96_url  = serializers.SerializerMethodField()
    size_192_url = serializers.SerializerMethodField()
    size_512_url = serializers.SerializerMethodField()
    url          = serializers.SerializerMethodField()  # default pick

    class Meta:
        model = EmblemAvatar
        fields = (
            "id", "seed", "initials", "fg", "bg",
            "size_48","size_96","size_192","size_512",          # raw keys
            "size_48_url","size_96_url","size_192_url","size_512_url",
            "url",
        )

    def _url(self, key): return key_to_url(key)
    def get_size_48_url(self, o):  return self._url(o.size_48)
    def get_size_96_url(self, o):  return self._url(o.size_96)
    def get_size_192_url(self, o): return self._url(o.size_192)
    def get_size_512_url(self, o): return self._url(o.size_512)
    def get_url(self, o):
        return self._url(o.size_96) or self._url(o.size_48) \
            or self._url(o.size_192) or self._url(o.size_512)


