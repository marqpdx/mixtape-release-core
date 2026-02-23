# stackroom/services/puddlejump_export.py
"""
Puddlejump Export Service (Puddlejump v1 Sections 7, 10, Appendix A3/A4).

Builds portable Canon bundles as zip files containing:
- puddlejump.json (machine manifest)
- PUDDLEJUMP.md (human catalog)
- Documents/*.md (canon documents with front matter)

Export is synchronous — available immediately after Canon approval (A4).
"""
from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone

from django.utils import timezone as dj_timezone

from stackroom.models import Library, SourceFile, SourceFileVersion, CanonApproval


def export_bundle(library: Library, include_non_canonical: bool = False) -> io.BytesIO:
    """
    Export a Library as a Puddlejump zip bundle.

    Args:
        library: The Library to export.
        include_non_canonical: If True, include all files (not just Canon).

    Returns:
        BytesIO containing the zip file.
    """
    # Collect source files
    qs = library.source_files.select_related("canon_version")
    if not include_non_canonical:
        qs = qs.filter(is_canon=True)

    source_files = list(qs)

    # Build document entries
    file_entries = []
    document_contents = {}  # path -> content string

    for sf in source_files:
        content = _get_export_content(sf)
        front_matter = _build_front_matter(sf)

        # Prepend front matter to content
        if front_matter:
            full_content = f"---\n{front_matter}---\n\n{content}"
        else:
            full_content = content

        doc_path = sf.path if sf.path else sf.filename
        # Ensure path is under Documents/
        if not doc_path.startswith("Documents/"):
            doc_path = f"Documents/{doc_path}"

        content_bytes = full_content.encode("utf-8")
        content_hash = hashlib.sha256(content_bytes).hexdigest()

        file_entries.append({
            "path": doc_path.removeprefix("Documents/"),
            "hash": f"sha256:{content_hash}",
            "size_bytes": len(content_bytes),
            "last_modified": sf.updated_at.isoformat() if sf.updated_at else datetime.now(timezone.utc).isoformat(),
            "canonical": sf.is_canon,
            "canonical_metadata": _get_canonical_metadata(sf) if sf.is_canon else None,
            "tags": [],
            "summary": "",
        })
        document_contents[doc_path] = full_content

    # Build catalog
    catalog_content = _build_catalog(library, file_entries)
    catalog_hash = hashlib.sha256(catalog_content.encode("utf-8")).hexdigest()

    # Build integrity
    all_hashes = "".join(e["hash"].removeprefix("sha256:") for e in file_entries)
    total_hash = hashlib.sha256(all_hashes.encode("utf-8")).hexdigest()

    # Build manifest
    bundle_id = str(uuid.uuid4())
    manifest = {
        "$schema": "https://puddlejump.mixtape.ai/schema/v1.0.json",
        "format_version": "1.0.0",
        "bundle": {
            "id": bundle_id,
            "title": library.title,
            "description": library.summary or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "mixtape-export",
        },
        "constraints": {
            "max_files": 300,
            "format": "markdown",
            "folder_depth": 5,
        },
        "files": file_entries,
        "integrity": {
            "catalog_hash": f"sha256:{catalog_hash}",
            "total_hash": f"sha256:{total_hash}",
            "algorithm": "sha256",
        },
        "generation": {
            "tool": "mixtape-export",
            "version": "1.0.0",
        },
    }

    # Build zip
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("puddlejump.json", json.dumps(manifest, indent=2))
        zf.writestr("PUDDLEJUMP.md", catalog_content)
        for doc_path, content in document_contents.items():
            zf.writestr(doc_path, content)

    # Update library export timestamp
    library.puddlejump_exported_at = dj_timezone.now()
    library.save(update_fields=["puddlejump_exported_at", "updated_at"])

    zip_buffer.seek(0)
    return zip_buffer


def _get_export_content(source_file: SourceFile) -> str:
    """Get the content to export for a source file."""
    # Prefer canon version snapshot
    if source_file.canon_version:
        return source_file.canon_version.content_snapshot

    # Fall back to latest version
    latest = (
        SourceFileVersion.objects
        .filter(source_file=source_file)
        .order_by("-version_number")
        .first()
    )
    if latest:
        return latest.content_snapshot

    # Fall back to artifact text
    artifact = source_file.artifacts.filter(
        artifact_type="normalized_markdown"
    ).first()
    if artifact and artifact.text:
        return artifact.text

    artifact = source_file.artifacts.first()
    if artifact and artifact.text:
        return artifact.text

    return ""


def _build_front_matter(source_file: SourceFile) -> str:
    """
    Build YAML front matter for export (§10, A3).

    Includes canonical metadata and AI-assistance transparency block.
    """
    lines = []

    if source_file.is_canon:
        lines.append("canonical: true")

        # Get approval info
        approval = (
            CanonApproval.objects
            .filter(source_file=source_file)
            .select_related("approved_by")
            .order_by("-approved_at")
            .first()
        )
        if approval:
            if approval.approved_by:
                lines.append(f'last_approved_by: "{approval.approved_by.username}"')
            lines.append(f'last_approved_at: "{approval.approved_at.isoformat()}"')

        # AI-assistance transparency (A3)
        ai_versions = (
            SourceFileVersion.objects
            .filter(source_file=source_file, ai_assisted=True)
            .order_by("version_number")
        )

        # If canon_version exists, only include AI assistance since last approval
        if source_file.canon_version:
            previous_approval = (
                CanonApproval.objects
                .filter(source_file=source_file)
                .order_by("-approved_at")
                .first()
            )
            if previous_approval:
                ai_versions = ai_versions.filter(
                    created_at__gte=previous_approval.approved_at
                )

        ai_entries = list(ai_versions)
        if ai_entries:
            lines.append("ai_assisted: true")
            lines.append("ai_assistance:")
            for v in ai_entries:
                lines.append(f'  - agent: "{v.ai_agent}"')
                lines.append(f'    date: "{v.created_at.strftime("%Y-%m-%d")}"')
                if v.ai_summary:
                    lines.append(f'    contribution: "{v.ai_summary}"')

    if not lines:
        return ""

    return "\n".join(lines) + "\n"


def _get_canonical_metadata(source_file: SourceFile) -> dict:
    """Get canonical metadata for manifest file entry."""
    approval = (
        CanonApproval.objects
        .filter(source_file=source_file)
        .select_related("approved_by")
        .order_by("-approved_at")
        .first()
    )

    meta = {}
    if approval:
        meta["date"] = approval.approved_at.strftime("%Y-%m-%d")
        if approval.approved_by:
            meta["authority"] = approval.approved_by.username
    return meta


def _build_catalog(library: Library, file_entries: list) -> str:
    """
    Build PUDDLEJUMP.md human-readable catalog (§7.3).
    """
    lines = [
        f"# {library.title}",
        "",
    ]

    if library.summary:
        lines.append(library.summary)
        lines.append("")

    lines.append("## Documents")
    lines.append("")

    canon_files = [f for f in file_entries if f["canonical"]]
    other_files = [f for f in file_entries if not f["canonical"]]

    if canon_files:
        lines.append("### Canonical")
        lines.append("")
        for f in sorted(canon_files, key=lambda x: x["path"]):
            lines.append(f"- `{f['path']}`")
        lines.append("")

    if other_files:
        lines.append("### Other")
        lines.append("")
        for f in sorted(other_files, key=lambda x: x["path"]):
            lines.append(f"- `{f['path']}`")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*Exported from Mixtape on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}*")
    lines.append("")

    return "\n".join(lines)
