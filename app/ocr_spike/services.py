from __future__ import annotations

import base64
import logging
import mimetypes
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from inkwell.client import InkwellUnavailableError, service_recognize_ocr_page

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
