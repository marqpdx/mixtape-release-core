# groups/api/presentation_views.py
#
# Tier 2 presentation PATCH and Tier 3 action vocabulary API.
# All writes require Steward or above.
# The contrast gate on setPalette is the load-bearing Tier 3 piece —
# it must exist server-side before any wizard UI is built.

import re
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.api.permissions import IsGroupStewardOrAbove
from groups.models import Group
from groups.models.group_public_config import GroupPublicConfig


# ---------------------------------------------------------------------------
# WCAG contrast gate
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
WCAG_MIN_RATIO = 4.5

_PALETTE_ROLES = {"bg", "bgSecondary", "surface", "accent", "text", "textSecondary", "border"}
_PALETTE_MODES = {"light", "dark", "lightHighContrast", "darkHighContrast"}

# Ten-font shortlist from the spec
_FONT_IDS = {
    "source-serif-4", "newsreader", "literata", "lora", "instrument-serif",
    "public-sans", "archivo", "work-sans", "karla", "ibm-plex-sans",
}

_TEMPLATE_IDS = {"masthead", "ledger", "atlas", "docket"}
_TYPE_RATIOS = {1.2, 1.25, 1.333}
_DENSITY_STEPS = {1, 2, 3}


def _relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def linearize(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def _contrast_ratio(hex1: str, hex2: str) -> float:
    l1 = _relative_luminance(hex1)
    l2 = _relative_luminance(hex2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def _validate_hex(value: str) -> bool:
    return bool(_HEX_RE.match(value))


def _run_contrast_gate(overrides: dict, mode: str) -> dict | None:
    """
    After any palette write, check accent vs bg in the affected mode.
    Returns None on pass; returns error dict on failure.
    """
    palette = overrides.get("palette", {})
    mode_palette = palette.get(mode, {})
    accent = mode_palette.get("accent")
    bg = mode_palette.get("bg")
    if not accent or not bg:
        return None
    ratio = _contrast_ratio(accent, bg)
    if ratio < WCAG_MIN_RATIO:
        return {
            "error": "contrast_gate",
            "ratio": ratio,
            "required": WCAG_MIN_RATIO,
            "pair": ["accent", "bg"],
            "mode": mode,
        }
    return None


# ---------------------------------------------------------------------------
# Tier 2 presentation PATCH
# (Sets template_id, palette_id, font_id, typography_setting on the config)
# ---------------------------------------------------------------------------

class GroupPresentationView(APIView):
    """
    PATCH /api/groups/<slug>/public-config/presentation

    Updates the four Tier 1/2 presentation fields on GroupPublicConfig.
    Creates the config record if it doesn't exist yet.
    """
    permission_classes = [IsGroupStewardOrAbove]

    def patch(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        config, _ = GroupPublicConfig.objects.get_or_create(group=group)

        errors = {}
        update_fields = ["updated_at"]

        typography_setting = request.data.get("typography_setting")
        if typography_setting is not None:
            valid = [c[0] for c in GroupPublicConfig._meta.get_field("typography_setting").choices]
            if typography_setting not in valid:
                errors["typography_setting"] = f"Must be one of: {valid}"
            else:
                config.typography_setting = typography_setting
                update_fields.append("typography_setting")

        template_id = request.data.get("template_id")
        if template_id is not None:
            if template_id != "" and template_id not in _TEMPLATE_IDS:
                errors["template_id"] = f"Must be one of: {sorted(_TEMPLATE_IDS)} or empty string."
            else:
                config.template_id = template_id
                update_fields.append("template_id")

        palette_id = request.data.get("palette_id")
        if palette_id is not None:
            valid = [c[0] for c in GroupPublicConfig._meta.get_field("palette_id").choices]
            if palette_id != "" and palette_id not in valid:
                errors["palette_id"] = f"Must be one of: {valid} or empty string."
            else:
                config.palette_id = palette_id
                update_fields.append("palette_id")

        font_id = request.data.get("font_id")
        if font_id is not None:
            if font_id != "" and font_id not in _FONT_IDS:
                errors["font_id"] = f"Must be one of: {sorted(_FONT_IDS)} or empty string."
            else:
                config.font_id = font_id
                update_fields.append("font_id")

        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        config.save(update_fields=update_fields)
        return Response({
            "typography_setting": config.typography_setting,
            "template_id": config.template_id or None,
            "palette_id": config.palette_id or None,
            "font_id": config.font_id or None,
        })


# ---------------------------------------------------------------------------
# Tier 3 action vocabulary
# ---------------------------------------------------------------------------

class GroupPresentationActionView(APIView):
    """
    POST /api/groups/<slug>/public-config/presentation/action

    Applies a single Tier 3 action vocabulary call. The agent emits validated
    calls — not markup or CSS. Returns the updated presentation_overrides on
    success; returns an error dict (with ratio) on contrast gate failure.

    Actions: setTemplate, setPalette, setType, setZoneOrder, setZoneVariant,
             toggleZone, setDensity.
    """
    permission_classes = [IsGroupStewardOrAbove]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        config, _ = GroupPublicConfig.objects.get_or_create(group=group)

        action = request.data.get("action")
        params = request.data.get("params", {})

        if not action:
            return Response({"detail": "'action' is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(params, dict):
            return Response({"detail": "'params' must be an object."}, status=status.HTTP_400_BAD_REQUEST)

        handler = getattr(self, f"_action_{action}", None)
        if handler is None:
            return Response(
                {"detail": f"Unknown action '{action}'. Valid actions: setTemplate, setPalette, setType, setZoneOrder, setZoneVariant, toggleZone, setDensity."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        overrides = config.presentation_overrides or {}
        result = handler(overrides, params)

        if isinstance(result, Response):
            return result

        # result is the mutated overrides dict — run contrast gate on setPalette writes
        if action == "setPalette":
            gate = _run_contrast_gate(result, params.get("mode", ""))
            if gate:
                return Response({"ok": False, **gate}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        config.presentation_overrides = result
        config.save(update_fields=["presentation_overrides", "updated_at"])
        return Response({"ok": True, "presentation_overrides": result})

    # -----------------------------------------------------------------------
    # Action handlers — each returns the mutated overrides dict or a Response
    # -----------------------------------------------------------------------

    def _action_setTemplate(self, overrides: dict, params: dict) -> dict | Response:
        template_id = params.get("id")
        if template_id not in _TEMPLATE_IDS:
            return Response(
                {"detail": f"'id' must be one of: {sorted(_TEMPLATE_IDS)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return {**overrides, "template_id": template_id}

    def _action_setPalette(self, overrides: dict, params: dict) -> dict | Response:
        role = params.get("role")
        hex_color = params.get("hex")
        mode = params.get("mode")

        if role not in _PALETTE_ROLES:
            return Response(
                {"detail": f"'role' must be one of: {sorted(_PALETTE_ROLES)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if mode not in _PALETTE_MODES:
            return Response(
                {"detail": f"'mode' must be one of: {sorted(_PALETTE_MODES)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not hex_color or not _validate_hex(hex_color):
            return Response(
                {"detail": "'hex' must be a 6-digit hex color string (e.g. '#7C2B23')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = dict(overrides)
        palette = dict(updated.get("palette", {}))
        mode_palette = dict(palette.get(mode, {}))
        mode_palette[role] = hex_color
        palette[mode] = mode_palette
        updated["palette"] = palette
        return updated

    def _action_setType(self, overrides: dict, params: dict) -> dict | Response:
        family = params.get("family")
        ratio = params.get("ratio")
        measure = params.get("measure")

        errors = {}
        if family not in _FONT_IDS:
            errors["family"] = f"Must be one of: {sorted(_FONT_IDS)}."
        if ratio not in _TYPE_RATIOS:
            errors["ratio"] = f"Must be one of: {sorted(_TYPE_RATIOS)}."
        if not isinstance(measure, (int, float)) or not (56 <= measure <= 76):
            errors["measure"] = "Must be a number between 56 and 76 (ch)."

        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        return {**overrides, "type": {"family": family, "ratio": ratio, "measure": measure}}

    def _action_setZoneOrder(self, overrides: dict, params: dict) -> dict | Response:
        zone_list = params.get("list")
        if not isinstance(zone_list, list) or not all(isinstance(z, str) for z in zone_list):
            return Response(
                {"detail": "'list' must be a list of zone name strings."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return {**overrides, "zone_order": zone_list}

    def _action_setZoneVariant(self, overrides: dict, params: dict) -> dict | Response:
        zone = params.get("zone")
        variant_id = params.get("id")
        if not zone or not isinstance(zone, str):
            return Response({"detail": "'zone' must be a non-empty string."}, status=status.HTTP_400_BAD_REQUEST)
        if not variant_id or not isinstance(variant_id, str):
            return Response({"detail": "'id' must be a non-empty string."}, status=status.HTTP_400_BAD_REQUEST)

        updated = dict(overrides)
        variants = dict(updated.get("zone_variants", {}))
        variants[zone] = variant_id
        updated["zone_variants"] = variants
        return updated

    def _action_toggleZone(self, overrides: dict, params: dict) -> dict | Response:
        zone = params.get("zone")
        enabled = params.get("enabled")
        if not zone or not isinstance(zone, str):
            return Response({"detail": "'zone' must be a non-empty string."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(enabled, bool):
            return Response({"detail": "'enabled' must be a boolean."}, status=status.HTTP_400_BAD_REQUEST)

        updated = dict(overrides)
        hidden = set(updated.get("hidden_zones", []))
        if enabled:
            hidden.discard(zone)
        else:
            hidden.add(zone)
        updated["hidden_zones"] = sorted(hidden)
        return updated

    def _action_setDensity(self, overrides: dict, params: dict) -> dict | Response:
        step = params.get("step")
        if step not in _DENSITY_STEPS:
            return Response(
                {"detail": f"'step' must be one of: {sorted(_DENSITY_STEPS)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return {**overrides, "density": step}
