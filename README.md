# Mixtape Release Core

Production Django backend for Mixtape, Crossroads, Catalyst, and related AI-native collaboration services.

This repository is private technical proof for a live production system. Mixtape has been live since April 2026 with over 99.99% uptime. The codebase has over 500 commits and is operated as part of a larger release constellation that includes frontend, realtime, ingestion, semantic memory, research, and governance repositories.

## What This System Does

Mixtape Core is the primary Django/DRF application layer for an AI-native collaboration and knowledge-stewardship platform. It supports groups, members, writing, publishing, curation, chat, initiatives, operational dashboards, Catalyst Codex ingestion, service authentication, and background processing.

The backend is designed around a practical production concern: humans and AI agents need to work with shared knowledge over time without losing permission boundaries, provenance, or operational clarity.

## Production Status

- Live production service since April 2026.
- Over 99.99% uptime since launch.
- Primary backend for real Mixtape/Crossroads users and groups.
- Operated with Django, Celery, RabbitMQ, PostgreSQL, Qdrant, service-authenticated internal APIs, and VPS deployment runbooks.
- Built and maintained by Mark A. Lilly as founder, principal architect, and primary developer.

## Technical Scope

Core capabilities represented in this repository include:

- Django REST Framework APIs for authenticated application surfaces.
- Group-scoped ownership and sponsorship patterns for user, group, and tenant-oriented content.
- Writing, draft, dispatch, publishing, and curation workflows.
- Catalyst Codex ingestion: source inventory, duplicate detection, human section review, shape-library-guided extraction, cached proposal bundles, and Markdown materialization.
- Background task orchestration with Celery and RabbitMQ.
- Service-to-service authentication using bearer/service JWT boundaries.
- Operational snapshots, management commands, data repair tools, and runbooks.
- Integrations with semantic memory, AI orchestration, ingestion/classification, and realtime services.

## Catalyst Resourcefulness Work

Catalyst is the knowledge-ingestion path used to turn messy source files into a structured Codex. Recent work refactored document parsing and ingest away from brute-force whole-document AI analysis and toward a human-curated, section-directed pipeline.

The current strategy produced a 91% token savings from that change alone while improving operator visibility and extraction accuracy. The important architectural shift is that human review becomes part of the data pipeline: source files are inventoried, sectioned, reviewed, mapped to domain shapes, cached as proposal bundles, and only then materialized into portable Markdown/JSON Codex artifacts.

Representative areas to review:

- `app/catalyst/`
- `app/catalyst/services/parse_service.py`
- `app/catalyst/services/shape_library.py`
- `app/catalyst/tasks.py`
- `app/catalyst/api/views.py`
- `app/claude/service.py`

## Architecture Notes

Mixtape Core treats PostgreSQL as the canonical application database while allowing derived knowledge artifacts to live in filesystem-backed Codex structures and downstream semantic-memory services. This keeps operational data, client-owned knowledge, derived AI artifacts, and public/private visibility rules distinct.

The backend is intentionally service-oriented without prematurely fragmenting the product into separate products. Django owns the core application state. Adjacent services such as Stackroom, Inkwell, Daedalus, Livewire, and Switchboard provide semantic memory, ingestion, research, realtime messaging, and AI orchestration boundaries.

## What To Look At First

For architectural review:

- `app/groups/` for group membership, ownership, and tenant-like boundaries.
- `app/writing/` for writing and publishing workflow.
- `app/catalyst/` for document ingestion and Codex generation.
- `app/initiatives/` for long-running work/session structures.
- `app/ops/` for application snapshots and operational visibility.
- `app/claude/` for CLI-backed AI session handling and token-accounting work.

For production-readiness review:

- Celery task definitions and queue routing.
- API permission classes and group-scoped access checks.
- Management commands used for import, repair, and operations.
- Migrations and model boundaries around content ownership.

## Requirements

- `requirements-dev.txt` - local development environment.
- `requirements-prod.txt` - production environment.

Legacy requirements files have been renamed:

- `zz_requirements.txt`
- `app/zz_requirements.txt`

## Privacy And Access

This repository is private because it contains the full implementation of a production platform. Access is granted selectively for technical review, hiring evaluation, or trusted collaboration. Sensitive secrets are not committed to the repository.
