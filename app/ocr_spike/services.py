from __future__ import annotations

import base64
import logging
import mimetypes
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from inkwell.client import InkwellUnavailableError, service_generate, service_recognize_ocr_page
from .shapes import (
    RECIPE_SHAPE_ID,
    generation_schema_for,
    load_shape,
    render_recipe_markdown,
    validate_recipe_shape,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedPage:
    page_number: int
    image_path: str
    width: int | None = None
    height: int | None = None


def prepare_artifact_pages(artifact) -> list[PreparedPage]:
    """
    Prepare reviewable OCR page images.

    Image uploads are already page images. PDF uploads are rasterized through
    Poppler's `pdftoppm`, which is portable to the target VPS and keeps OCR
    engines focused on image recognition.
    """
    content_type = artifact.content_type or mimetypes.guess_type(artifact.original_filename)[0] or ""
    if content_type == "application/pdf" or Path(artifact.original_filename).suffix.lower() == ".pdf":
        return _prepare_pdf_pages(artifact)
    return [PreparedPage(page_number=1, image_path=artifact.source_file_path)]


def recognize_page_with_inkwell(page, provider: str, engine: str | None = None) -> dict:
    artifact = page.artifact
    content_type = _content_type_for_page(page, artifact)

    with default_storage.open(page.image_path or artifact.source_file_path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")

    try:
        return service_recognize_ocr_page(
            filename=artifact.original_filename,
            content_type=content_type,
            file_base64=encoded,
            page_number=page.page_number,
            provider=provider,
            engine=engine,
        )
    except InkwellUnavailableError:
        raise
    except Exception as exc:
        logger.exception("[ocr_spike] unexpected Inkwell recognition error")
        raise InkwellUnavailableError(str(exc)) from exc


def shape_recipe_with_inkwell(*, text: str, page, selected_attempt=None) -> dict:
    shape = load_shape(RECIPE_SHAPE_ID)
    prompt = _recipe_shape_prompt(text=text, shape=shape, page=page)
    started = time.perf_counter()
    result = service_generate(
        system_prompt=(
            "You shape reviewed OCR text into a declared knowledge shape. "
            "Extract only what is present, preserve uncertainty, and return valid JSON only."
        ),
        prompt=prompt,
        schema=generation_schema_for(shape),
        max_tokens=2048,
        temperature=0.0,
        timeout_seconds=int(getattr(settings, "INKWELL_SHAPING_TIMEOUT_SECONDS", 240)),
    )
    shaped_json = result.get("result") or {}
    shaped_json["shape_id"] = shape.shape_id
    shaped_json["shape_version"] = shape.version
    validation_errors = validate_recipe_shape(shaped_json, shape)
    markdown = render_recipe_markdown(shaped_json)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "shape": shape,
        "model_name": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "input_text": text,
        "output_json": shaped_json,
        "output_markdown": markdown,
        "validation_errors": validation_errors,
        "processing_time_ms": elapsed_ms,
        "raw_result_json": result,
        "selected_attempt_id": str(selected_attempt.id) if selected_attempt else None,
    }


def _prepare_pdf_pages(artifact) -> list[PreparedPage]:
    renderer = getattr(settings, "OCR_SPIKE_PDF_RENDERER", "pdftoppm")
    if renderer != "pdftoppm":
        raise RuntimeError(f"Unsupported OCR PDF renderer: {renderer}")

    pdftoppm = shutil.which(getattr(settings, "OCR_SPIKE_PDFTOPPM_CMD", "pdftoppm"))
    if not pdftoppm:
        raise RuntimeError("PDF OCR requires Poppler `pdftoppm`; install poppler on the OCR worker/VPS")

    dpi = int(getattr(settings, "OCR_SPIKE_PDF_DPI", 220))
    max_pages = int(getattr(settings, "OCR_SPIKE_MAX_PDF_PAGES", 20))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        source_pdf = tmp_path / "source.pdf"
        output_prefix = tmp_path / "page"
        with default_storage.open(artifact.source_file_path, "rb") as source:
            source_pdf.write_bytes(source.read())

        cmd = [
            pdftoppm,
            "-png",
            "-r",
            str(dpi),
            "-f",
            "1",
            "-l",
            str(max_pages),
            str(source_pdf),
            str(output_prefix),
        ]
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=int(getattr(settings, "OCR_SPIKE_PDF_RENDER_TIMEOUT_SECONDS", 180)),
        )

        rendered = sorted(tmp_path.glob("page-*.png"))
        if not rendered:
            raise RuntimeError("PDF renderer did not produce any page images")

        pages: list[PreparedPage] = []
        for index, rendered_page in enumerate(rendered, start=1):
            image_path = f"ocr_spike/{artifact.id}/pages/page-{index:04d}.png"
            default_storage.save(image_path, ContentFile(rendered_page.read_bytes()))
            width, height = _image_dimensions(rendered_page)
            pages.append(PreparedPage(
                page_number=index,
                image_path=image_path,
                width=width,
                height=height,
            ))
        return pages


def _image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.width, image.height
    except Exception:
        logger.exception("[ocr_spike] could not read rendered image dimensions for %s", path)
        return None, None


def _content_type_for_page(page, artifact) -> str:
    if page.image_path and Path(page.image_path).suffix.lower() == ".png":
        return "image/png"
    return artifact.content_type or mimetypes.guess_type(artifact.original_filename)[0] or "application/octet-stream"


def _recipe_shape_prompt(*, text: str, shape, page) -> str:
    return f"""
Shape the reviewed OCR text as {shape.shape_id}@{shape.version}.

Page context:
- artifact: {page.artifact.original_filename}
- page_number: {page.page_number}

Shape extraction guidance:
{shape.extraction_guidance}

Return JSON matching the supplied schema. Do not include Markdown in JSON.
Use these exact fields:
- shape_id: {shape.shape_id}
- shape_version: {shape.version}

Rules:
- Do not invent missing recipe content.
- Preserve original ingredient lines in original_text when available.
- If OCR damage makes a field questionable, include it and mark uncertain.
- Keep recipe steps in source order.
- If this does not look like a recipe, still return the closest sparse recipe
  object and explain the mismatch in uncertain.

Reviewed OCR text:
```text
{text}
```
""".strip()
