# apps/identity/services/emblem_service.py

import io
import time
import requests
from PIL import Image, ImageDraw, ImageFont
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

class EmblemRenderer:
    """Generates and caches emblem images to SeaweedFS (S3-compatible)"""
    SIZES = [48, 96, 192, 512, (1200, 630)]  # Last one is OG image

    def __init__(self):
        self.storage = default_storage
        # Debug: do not assume attributes exist on default_storage
        print(f"[EMBLEM] Storage: {type(self.storage).__name__}")
        print(f"[EMBLEM] Storage custom_domain: {getattr(self.storage, 'custom_domain', None)}")
        print(f"[EMBLEM] Storage endpoint_url: {getattr(self.storage, 'endpoint_url', None)}")
        print(f"[EMBLEM] Storage bucket_name: {getattr(self.storage, 'bucket_name', None)}")
        print("\n***** *****\n")

    def render_and_upload(self, emblem_avatar):
        print(f"[EMBLEM] Starting render for {emblem_avatar.id}")
        start = time.time()
        try:
            if emblem_avatar.type.is_upload:
                success = self._handle_upload(emblem_avatar)
            else:
                engine = emblem_avatar.type.engine
                style  = emblem_avatar.type.style

                if engine == "dicebear":
                    success = self._render_dicebear(emblem_avatar, style)
                elif engine == "boring":
                    success = self._render_boring(emblem_avatar, style)
                elif engine == "initials":
                    success = self._render_initials(emblem_avatar)
                elif engine == "jdenticon":
                    success = self._render_jdenticon(emblem_avatar)
                else:
                    success = False

            print(f"[EMBLEM] Render completed in {time.time() - start:.2f}s")
            return success
        except Exception as e:
            print(f"[EMBLEM ERROR] Failed to render {emblem_avatar.id}: {e}")
            return False

    def _handle_upload(self, emblem):
        """For uploaded images, create resized versions from stored original KEY."""
        if not emblem.image_path:
            print("[EMBLEM ERROR] image_path empty for upload emblem")
            return False

        print(f"[EMBLEM] Processing upload key: {emblem.image_path}")
        try:
            # Prefer reading from storage (image_path is a KEY)
            if isinstance(emblem.image_path, str) and emblem.image_path.startswith(("http://", "https://")):
                # Back-compat: older rows that stored a URL
                resp = requests.get(emblem.image_path, timeout=10)
                resp.raise_for_status()
                original = Image.open(io.BytesIO(resp.content))
            else:
                with self.storage.open(emblem.image_path, "rb") as f:
                    original = Image.open(io.BytesIO(f.read()))

            if original.mode != "RGB":
                original = original.convert("RGB")
        except Exception as e:
            print(f"[EMBLEM ERROR] Failed to open original: {e}")
            return False

        wrote = 0
        for size in self.SIZES:
            if isinstance(size, tuple):
                w, h = size
                resized = self._resize_cover(original, w, h)
                saved_key = self._upload_image(resized, emblem, f"og_{w}x{h}")
                emblem.og_1200x630 = saved_key
                wrote += 1
            else:
                resized  = self._resize_contain(original.copy(), size, size)
                saved_key = self._upload_image(resized, emblem, f"size_{size}")
                setattr(emblem, f"size_{size}", saved_key)
                wrote += 1

        if wrote:
            self._save_without_signal(emblem)
        return wrote > 0

    def _render_dicebear(self, emblem, style):
        seed = emblem.seed or str(emblem.id)
        bg   = emblem.bg.replace("#", "") if emblem.bg else None

        base_url = f"https://api.dicebear.com/9.x/{style}/svg"
        params = {"seed": seed, "radius": 10, "scale": 100}
        if bg:
            params["backgroundColor"] = bg

        print(f"[EMBLEM] Generating DiceBear {style} with seed: {seed}")

        success_count = 0
        for size in [s for s in self.SIZES if not isinstance(s, tuple)]:
            try:
                params["size"] = size
                response = requests.get(base_url, params=params, timeout=10)
                response.raise_for_status()

                svg_data = response.content
                print(f"[EMBLEM] Fetched SVG for {size}px: {len(svg_data)} bytes")

                img = self._svg_to_png(svg_data, size)
                print(f"[EMBLEM] Converted to PNG: {img.size}")

                saved_key = self._upload_image(img, emblem, f"size_{size}")
                print(f"[EMBLEM] Uploaded key: {saved_key}")

                setattr(emblem, f"size_{size}", saved_key)
                print(f"[EMBLEM] Set attribute size_{size}")
                success_count += 1
            except Exception as e:
                print(f"[EMBLEM ERROR] Failed {size}px: {type(e).__name__}: {e}")
                continue

        print(f"[EMBLEM] Successfully processed {success_count}/4 sizes")
        if success_count == 0:
            print("[EMBLEM ERROR] No sizes were generated - aborting")
            return False

        self._save_without_signal(emblem)
        return True

    def _upload_image(self, img, emblem, suffix) -> str:
        """Upload image and return the STORAGE KEY (not URL)."""
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True, quality=85)
        file_size = buf.tell()
        buf.seek(0)

        key = f"emblems/{emblem.id}/{suffix}.png"
        print(f"[EMBLEM] Uploading {key} ({file_size} bytes)")
        saved_key = self.storage.save(key, ContentFile(buf.read()))
        print(f"[EMBLEM] Saved key: {saved_key}")
        return saved_key

    def _render_initials(self, emblem):
        initials = emblem.initials or "?"
        fg = emblem.fg or "#FFFFFF"
        bg = emblem.bg or "#2F855A"
        print(f"[EMBLEM] Generating initials: {initials}")

        wrote = 0
        for size in [s for s in self.SIZES if not isinstance(s, tuple)]:
            img = Image.new("RGB", (size, size), bg)
            draw = ImageDraw.Draw(img)

            font_size = int(size * 0.4)
            try:
                font_paths = [
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/System/Library/Fonts/Helvetica.ttc",
                    "C:\\Windows\\Fonts\\arial.ttf",
                ]
                font = None
                for path in font_paths:
                    try:
                        font = ImageFont.truetype(path, font_size)
                        break
                    except Exception:
                        continue
                if not font:
                    font = ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), initials, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            pos = ((size - text_w) // 2, (size - text_h) // 2)
            draw.text(pos, initials, fill=fg, font=font)

            saved_key = self._upload_image(img, emblem, f"size_{size}")
            setattr(emblem, f"size_{size}", saved_key)
            wrote += 1

        if wrote:
            self._save_without_signal(emblem)
        return wrote > 0

    def _save_without_signal(self, emblem):
        """Save emblem without triggering post_save signal to avoid recursion"""
        from django.db.models.signals import post_save
        from identity.models import EmblemAvatar

        print(f"[EMBLEM] About to save {emblem.id}")
        prev = emblem.size_96[:80] if getattr(emblem, "size_96", None) else "empty"
        print(f"[EMBLEM] size_96 before save: '{prev}...'")

        post_save.disconnect(render_emblem_on_save, sender=EmblemAvatar)
        try:
            # Save only fields that are present to avoid overwriting accidentally
            fields = []
            for fld in ("size_48","size_96","size_192","size_512","og_1200x630"):
                if getattr(emblem, fld, None):
                    fields.append(fld)
            emblem.save(update_fields=fields or None)

            emblem.refresh_from_db()
            after = emblem.size_96[:80] if getattr(emblem, "size_96", None) else "empty"
            print(f"[EMBLEM] size_96 after refresh: '{after}...'")
        except Exception as e:
            print(f"[EMBLEM ERROR] Save failed: {e}")
        finally:
            post_save.connect(render_emblem_on_save, sender=EmblemAvatar)

    def _svg_to_png(self, svg_data: bytes, size: int) -> Image.Image:
        """
        Convert SVG bytes → PNG Pillow Image at square size.
        Tries cairosvg; falls back to a placeholder if unavailable.
        """
        try:
            import cairosvg  # requires libcairo on Ubuntu
            png_bytes = cairosvg.svg2png(
                bytestring=svg_data,
                output_width=size,
                output_height=size,
            )
            return Image.open(io.BytesIO(png_bytes)).convert("RGB")
        except Exception as e:
            print(f"[EMBLEM WARN] svg→png failed ({type(e).__name__}: {e}); using placeholder")
            img = Image.new("RGB", (size, size), "#E2E8F0")
            draw = ImageDraw.Draw(img)
            txt = "SVG"
            w, h = draw.textlength(txt), 10
            draw.text(((size - w)//2, (size - h)//2), txt, fill="#4A5568")
            return img

    def _resize_contain(self, img: Image.Image, w: int, h: int) -> Image.Image:
        """
        Fit within (w,h), preserving aspect (letterboxing with transparent background not needed here).
        """
        out = img.copy()
        out.thumbnail((w, h))
        if out.mode != "RGB":
            out = out.convert("RGB")
        canvas = Image.new("RGB", (w, h), "#FFFFFF")
        ox = (w - out.width) // 2
        oy = (h - out.height) // 2
        canvas.paste(out, (ox, oy))
        return canvas

    def _resize_cover(self, img: Image.Image, w: int, h: int) -> Image.Image:
        """
        Fill (w,h) by cropping to cover, preserving aspect.
        """
        src_w, src_h = img.size
        if src_w == 0 or src_h == 0:
            return Image.new("RGB", (w, h), "#FFFFFF")

        src_ratio = src_w / src_h
        dst_ratio = w / h

        if src_ratio > dst_ratio:
            # wider → height matches, crop width
            new_h = h
            new_w = int(h * src_ratio)
        else:
            # taller → width matches, crop height
            new_w = w
            new_h = int(w / src_ratio)

        resized = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - w) // 2
        top = (new_h - h) // 2
        right = left + w
        bottom = top + h
        out = resized.crop((left, top, right, bottom))
        if out.mode != "RGB":
            out = out.convert("RGB")
        return out



# Signal to auto-render on creation
from django.db.models.signals import post_save
from django.dispatch import receiver
from identity.models import EmblemAvatar

@receiver(post_save, sender=EmblemAvatar)
def render_emblem_on_save(sender, instance, created, raw, **kwargs):
    """
    Automatically render emblems when:
    1. First created (lazy rendering)
    2. Missing cached images (re-render needed)

    Skip during fixtures/loaddata (raw=True)
    """
    if raw:
        return

    # Only render if missing images
    if not instance.size_96:
        print(f"[EMBLEM] Triggering render for {instance.id}")

        # TODO: In production, use Celery/RQ for async:
        # from identity.tasks import render_emblem_task
        # render_emblem_task.delay(instance.id)

        renderer = EmblemRenderer()
        renderer.render_and_upload(instance)