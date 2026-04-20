import logging

from celery import shared_task

logger = logging.getLogger(__name__)


def _extract_text_from_file(file_field, file_kind):
    file_field.open("rb")
    try:
        raw = file_field.read()
    finally:
        file_field.close()

    if file_kind == "md":
        return raw.decode("utf-8", errors="replace")

    if file_kind == "pdf":
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(p.strip() for p in pages if p.strip())

    if file_kind == "docx":
        import io
        from docx import Document
        doc = Document(io.BytesIO(raw))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

    # other: try UTF-8 decode, fall back to empty
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


@shared_task(
    name="prospects.tasks.parse_prospect_file_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def parse_prospect_file_task(self, response_id):
    from .models import ProspectResponse

    try:
        response = ProspectResponse.objects.get(id=response_id)
    except ProspectResponse.DoesNotExist:
        logger.warning(f"ProspectResponse {response_id} not found — skipping parse")
        return

    response.processing_status = "processing"
    response.save(update_fields=["processing_status"])

    try:
        text = _extract_text_from_file(response.source_file, response.file_kind)
        response.response_text = text
        response.processing_status = "done"
        response.processing_error = ""
        response.save(update_fields=["response_text", "processing_status", "processing_error", "updated_at"])
    except Exception as exc:
        logger.exception(f"File parse failed for ProspectResponse {response_id}: {exc}")
        response.processing_status = "failed"
        response.processing_error = str(exc)
        response.save(update_fields=["processing_status", "processing_error", "updated_at"])
        raise self.retry(exc=exc)
