"""
Ariadne — Puddlejump corpus connector (build spec §4, Phase P1).

Direct filesystem read of the Puddlejump repo, decided 2026-10-09
(decisions/ariadne/ariadne-build-spec.md §2) — not through Stackroom's
canon-bundle-replica MCP path. Ariadne reads; it never writes. Puddlejump
remains sole canon authority.

This module has no Django dependency on purpose: it's usable as a plain
CLI (`python -m ariadne.corpus`) before any schema (P4) or app registration
(P3) exists, matching the P1 checkpoint's "no app/models, no live traffic"
risk posture (decisions/ariadne/ariadne-status.md).

Conventions here are carried over from the two read-only spikes that
validated them against the real corpus, not guessed:
  - decisions/ariadne/spike/p0-findings.md (corpus census, ADR heuristic)
  - decisions/spikes/puddlejump-frontmatter-coherence.md (frontmatter
    styles, stakes signaling)

Naming note: PyPI has an unrelated `ariadne` GraphQL package. This repo
does not depend on it (checked 2026-10-11), so the `ariadne` package name
is free here — but don't `pip install ariadne` (the GraphQL one) into
this project without renaming this package first.

Known gap, not yet addressed here: `stakes_tier`/`never-drift` only
exists in YAML frontmatter today. Blockquote-style docs (most ratified
ADRs) have no equivalent field — see the frontmatter coherence spike's
"Stakes signaling" section. This connector surfaces `is_adr` and raw
frontmatter but does not yet derive a stakes level; that's blocked on
the CTO's frontmatter-normalization decision, not on anything in here.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Corpus root
# ---------------------------------------------------------------------------

_DEFAULT_CORPUS_ROOT = (Path(__file__).resolve().parent.parent.parent.parent / "puddlejump").resolve()


def get_corpus_root() -> Path:
    """Resolve ARIADNE_PUDDLEJUMP_PATH, falling back to the sibling
    puddlejump checkout. Reads the env var directly rather than
    django.conf.settings so this module works standalone (P1 predates
    P3's app registration)."""
    configured = os.getenv("ARIADNE_PUDDLEJUMP_PATH")
    return Path(configured).resolve() if configured else _DEFAULT_CORPUS_ROOT


# Decided 2026-10-11 (CTO, off the back of the P0 spike): Ariadne's indexed
# corpus excludes append-only log directories by default. These are
# post-hoc logs, not conceptual documents. See ariadne-handoff.md.
EXCLUDED_DIRS = {
    ".git", ".claude",
    "build-log-inbox", "atrium-handoff-inbox", "file-catalog-inbox",
}

HEADER_BLOCK_RE = re.compile(r'^>\s+\*\*([^*]+)\*\*[:\s]+(.+)$')
YAML_FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n", re.DOTALL)
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

ADR_PATH_HINT_RE = re.compile(r"-adr/|/decisions/argus/audit-blocks/", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------

@dataclass
class Document:
    path: Path
    rel_path: str
    raw_text: str
    stripped_text: str  # code fences removed; for lexical analysis, not retrieval
    frontmatter_style: str  # "blockquote" | "yaml" | "none" | "yaml_parse_error"
    frontmatter: dict
    headings: list[tuple[int, str]]
    is_adr: bool
    content_hash: str  # revision fingerprint, build spec §4


def _parse_blockquote_frontmatter(text: str) -> dict:
    headers: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(">"):
            if headers:
                break
            continue
        m = HEADER_BLOCK_RE.match(line)
        if m:
            headers[m.group(1).strip().rstrip(":")] = m.group(2).strip()
    return headers


def _parse_yaml_frontmatter(text: str) -> dict | None:
    m = YAML_FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return None


def _classify_frontmatter(text: str) -> tuple[str, dict]:
    if text.startswith("---\n"):
        data = _parse_yaml_frontmatter(text)
        if data is None:
            return "yaml_parse_error", {}
        return "yaml", data
    headers = _parse_blockquote_frontmatter(text)
    if headers:
        return "blockquote", headers
    return "none", {}


def _classify_adr(rel_path: str, frontmatter: dict, style: str) -> bool:
    """Path/header metadata first, confirmed against the real corpus by the
    P0 spike — no title-heuristic fallback has been needed so far
    (ariadne-handoff.md, decided 2026-10-11)."""
    if style == "blockquote":
        if "ADR" in frontmatter:
            return True
        if "adr" in frontmatter.get("Class", "").lower():
            return True
    elif style == "yaml":
        if "adr" in str(frontmatter.get("kind", "")).lower():
            return True
        if "adr" in str(frontmatter.get("class", "")).lower():
            return True
    if ADR_PATH_HINT_RE.search(rel_path):
        return True
    return False


def _content_hash(raw_bytes: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"


def load_document(path: Path, corpus_root: Path) -> Document:
    raw_bytes = path.read_bytes()
    raw_text = raw_bytes.decode("utf-8", errors="replace")
    rel_path = str(path.relative_to(corpus_root)).replace("\\", "/")

    style, frontmatter = _classify_frontmatter(raw_text)
    headings = [(len(h), t.strip()) for h, t in HEADING_RE.findall(raw_text)]
    is_adr = _classify_adr(rel_path, frontmatter, style)

    # Code blocks excluded from lexical analysis by default, retained in
    # raw_text for retrieval (build spec §4).
    stripped = CODE_FENCE_RE.sub(" ", raw_text)
    stripped = INLINE_CODE_RE.sub(" ", stripped)

    return Document(
        path=path, rel_path=rel_path, raw_text=raw_text, stripped_text=stripped,
        frontmatter_style=style, frontmatter=frontmatter, headings=headings,
        is_adr=is_adr, content_hash=_content_hash(raw_bytes),
    )


def enumerate_documents(corpus_root: Path | None = None) -> list[Document]:
    """Enumerate eligible Markdown documents under the corpus root,
    excluding append-only log directories by default (EXCLUDED_DIRS)."""
    root = corpus_root or get_corpus_root()
    docs = []
    for path in sorted(root.rglob("*.md")):
        rel_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue
        docs.append(load_document(path, root))
    return docs


# ---------------------------------------------------------------------------
# Manifest — for sanity-checking this module against the spikes' findings
# ---------------------------------------------------------------------------

def build_manifest(docs: list[Document]) -> dict:
    from collections import Counter

    by_style = Counter(d.frontmatter_style for d in docs)
    by_top_dir = Counter(d.rel_path.split("/")[0] if "/" in d.rel_path else "(root)" for d in docs)
    adr_count = sum(1 for d in docs if d.is_adr)

    return {
        "total_documents": len(docs),
        "by_frontmatter_style": dict(by_style),
        "by_top_level_directory": dict(by_top_dir.most_common()),
        "adr_classified_count": adr_count,
    }


def _cli() -> None:
    root = get_corpus_root()
    print(f"Corpus root: {root}")
    docs = enumerate_documents(root)
    manifest = build_manifest(docs)
    print(f"Documents: {manifest['total_documents']}")
    print(f"Frontmatter styles: {manifest['by_frontmatter_style']}")
    print(f"ADR-classified: {manifest['adr_classified_count']}")
    print(f"Top-level directories: {manifest['by_top_level_directory']}")


if __name__ == "__main__":
    _cli()
