# stackroom/services/puddlejump_import.py

"""
Puddlejump Import Service - Phase 2

Handles the actual import processing of validated Puddlejump bundles.
Creates Library and LibraryItem records from bundle contents.

Phase 2 Scope:
- Create Library record
- Create LibraryItem records (with folder hierarchy)
- Store canonical metadata (from file front matter)
- Link to sponsor (User or Group)

NOT in Phase 2:
- Stackroom ingestion (Phase 3)
- SourceFile creation (Phase 3)
- Conflict detection (Phase 3)
"""

from __future__ import annotations

import json
import yaml
import zipfile
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from django.db import transaction
from django.utils.text import slugify
from django.contrib.contenttypes.models import ContentType

from stackroom.models import Library, LibraryItem

logger = logging.getLogger(__name__)


class PuddlejumpImportService:
    """
    Service for importing Puddlejump bundles into Mixtape.

    Phase 2: Creates Library and LibraryItem records only.
    """

    def __init__(self, user, sponsor):
        """
        Initialize import service.

        Args:
            user: User performing the import
            sponsor: Sponsor (User or Group) that will own the Library
        """
        self.user = user
        self.sponsor = sponsor

    @transaction.atomic
    def import_bundle(
        self,
        zip_file,
        manifest: Dict[str, Any],
        conflict_strategy: str = 'replace'
    ) -> Dict[str, Any]:
        """
        Import a validated Puddlejump bundle.

        Args:
            zip_file: Uploaded file object (already validated)
            manifest: Parsed manifest dict (from validation)
            conflict_strategy: How to handle conflicts ('replace' | 'version' | 'skip')

        Returns:
            {
                "library_id": str,
                "library_slug": str,
                "bundle_id": str,
                "status": str,
                "counts": {...},
                "created_at": str
            }
        """
        bundle_metadata = manifest['bundle']
        file_entries = manifest.get('files', [])

        logger.info(
            f"Starting import of bundle {bundle_metadata['id']} "
            f"for user {self.user.id}"
        )

        # Step 1: Create or update Library
        library = self._create_or_update_library(bundle_metadata, manifest)

        # Step 2: Extract bundle to temp directory
        temp_dir = self._extract_bundle(zip_file)

        try:
            # Step 3: Create folder structure and items
            created_items = self._create_library_items(
                library=library,
                file_entries=file_entries,
                temp_dir=temp_dir
            )

            # Step 4: Update Library metadata
            library.puddlejump_exported_at = None  # Clear export timestamp
            library.save()

            return {
                "library_id": str(library.id),
                "library_slug": library.slug,
                "bundle_id": bundle_metadata['id'],
                "status": "completed",
                "counts": {
                    "total_files": len(file_entries),
                    "new_files": len(created_items),
                    "updated_files": 0,  # Phase 3 will handle updates
                    "skipped_files": 0,
                    "conflicts": 0
                },
                "created_at": datetime.utcnow().isoformat() + "Z"
            }

        finally:
            # Cleanup temp directory
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _create_or_update_library(
        self,
        bundle_metadata: Dict[str, Any],
        manifest: Dict[str, Any]
    ) -> Library:
        """
        Create new Library or update existing one (based on bundle_id).

        Args:
            bundle_metadata: Bundle metadata from manifest
            manifest: Full manifest dict

        Returns:
            Library instance
        """
        bundle_id = bundle_metadata['id']

        # Check if library with this bundle_id already exists
        existing = Library.objects.filter(
            puddlejump_bundle_id=bundle_id
        ).first()

        if existing:
            logger.info(f"Updating existing library {existing.id} for bundle {bundle_id}")
            library = existing
            # Update metadata
            library.title = bundle_metadata.get('title', library.title)
            library.summary = bundle_metadata.get('description', library.summary)
            library.save()
        else:
            # Create new library
            logger.info(f"Creating new library for bundle {bundle_id}")

            # Get sponsor content type
            sponsor_ct = ContentType.objects.get_for_model(self.sponsor)

            library = Library.objects.create(
                title=bundle_metadata['title'],
                slug=self._generate_unique_slug(bundle_metadata['title']),
                summary=bundle_metadata.get('description', ''),
                sponsor_content_type=sponsor_ct,
                sponsor_object_id=self.sponsor.id,
                author=self.user,
                submitted_by=self.user,
                puddlejump_bundle_id=bundle_id,
                puddlejump_origin='imported'
            )

        return library

    def _generate_unique_slug(self, title: str) -> str:
        """
        Generate unique slug for library.

        Args:
            title: Library title

        Returns:
            Unique slug string
        """
        base_slug = slugify(title)
        slug = base_slug
        counter = 1

        # Ensure slug is unique
        while Library.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        return slug

    def _extract_bundle(self, zip_file) -> Path:
        """
        Extract bundle to temporary directory.

        Args:
            zip_file: Uploaded file object

        Returns:
            Path to extracted directory
        """
        temp_dir = Path(tempfile.mkdtemp(prefix='puddlejump_'))

        # Write uploaded file to temp location
        temp_zip_path = temp_dir / 'bundle.zip'
        with open(temp_zip_path, 'wb') as f:
            for chunk in zip_file.chunks():
                f.write(chunk)

        # Extract zip
        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        # Remove zip file
        temp_zip_path.unlink()

        return temp_dir

    def _create_library_items(
        self,
        library: Library,
        file_entries: List[Dict[str, Any]],
        temp_dir: Path
    ) -> List[LibraryItem]:
        """
        Create LibraryItem records for all files in bundle.

        Creates folder hierarchy and file items.

        Args:
            library: Library to add items to
            file_entries: File entries from manifest
            temp_dir: Path to extracted bundle

        Returns:
            List of created LibraryItem instances
        """
        # Clear existing items (for re-import)
        library.items.all().delete()

        created_items = []
        folder_cache: Dict[str, LibraryItem] = {}  # path -> LibraryItem

        # Sort files by path to ensure folders are created before contents
        sorted_entries = sorted(file_entries, key=lambda x: x['path'])

        for idx, entry in enumerate(sorted_entries):
            file_path = entry['path']
            is_canonical = entry.get('canonical', False)
            canonical_metadata = entry.get('canonical_metadata', {})

            # Parse file path
            path_parts = Path(file_path).parts
            parent_folder_path = str(Path(*path_parts[:-1])) if len(path_parts) > 1 else ''

            # Ensure parent folders exist
            if parent_folder_path:
                parent_item = self._ensure_folder_exists(
                    library=library,
                    folder_path=parent_folder_path,
                    folder_cache=folder_cache
                )
            else:
                parent_item = None

            # Read file content to extract front matter
            file_full_path = temp_dir / 'Documents' / file_path
            front_matter = self._extract_front_matter(file_full_path)

            # Merge canonical metadata (front matter takes precedence)
            if front_matter:
                is_canonical = front_matter.get('canonical', is_canonical)
                if is_canonical:
                    canonical_metadata = {
                        'canonical_date': front_matter.get('canonical_date'),
                        'canonical_authority': front_matter.get('canonical_authority'),
                        'supersedes': front_matter.get('supersedes'),
                        'review_date': front_matter.get('review_date'),
                    }

            # Create LibraryItem (file)
            # Note: In Phase 2, we create items WITHOUT content_object
            # Phase 3 will create SourceFile and link it
            item = LibraryItem.objects.create(
                library=library,
                is_folder=False,
                title=Path(file_path).name,  # Store filename as title for now
                parent=parent_item,
                order_index=idx,
                folder_path=file_path,  # Store full path for reference
                is_featured=is_canonical,  # Cache canonical status
                puddlejump_canonical_metadata=canonical_metadata if is_canonical else {},
                tags=front_matter.get('tags', []) if front_matter else [],
                notes=front_matter.get('summary', '') if front_matter else ''
            )

            created_items.append(item)
            logger.debug(f"Created item for {file_path} (canonical: {is_canonical})")

        logger.info(f"Created {len(created_items)} library items")
        return created_items

    def _ensure_folder_exists(
        self,
        library: Library,
        folder_path: str,
        folder_cache: Dict[str, LibraryItem]
    ) -> LibraryItem:
        """
        Ensure folder exists in hierarchy, creating parent folders as needed.

        Args:
            library: Library to add folder to
            folder_path: Relative folder path (e.g., "guides/advanced")
            folder_cache: Cache of already created folders

        Returns:
            LibraryItem for the folder
        """
        if folder_path in folder_cache:
            return folder_cache[folder_path]

        path_parts = Path(folder_path).parts
        parent_item = None

        # Create each level of folder hierarchy
        for i in range(len(path_parts)):
            current_path = str(Path(*path_parts[:i+1]))

            if current_path in folder_cache:
                parent_item = folder_cache[current_path]
                continue

            # Create folder item
            folder_item = LibraryItem.objects.create(
                library=library,
                is_folder=True,
                title=path_parts[i],  # Folder name
                parent=parent_item,
                order_index=0,  # Folders sorted first
                folder_path=current_path
            )

            folder_cache[current_path] = folder_item
            parent_item = folder_item

            logger.debug(f"Created folder: {current_path}")

        return folder_cache[folder_path]

    def _extract_front_matter(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Extract YAML front matter from markdown file.

        Args:
            file_path: Path to markdown file

        Returns:
            Dict of front matter data, or None if no front matter
        """
        if not file_path.exists():
            return None

        try:
            content = file_path.read_text(encoding='utf-8')

            # Check for YAML front matter (between --- delimiters)
            if not content.startswith('---'):
                return None

            # Find closing delimiter
            end_idx = content.find('\n---\n', 3)
            if end_idx == -1:
                end_idx = content.find('\n---\r\n', 3)
            if end_idx == -1:
                return None

            # Extract and parse YAML
            front_matter_text = content[3:end_idx]
            front_matter = yaml.safe_load(front_matter_text)

            return front_matter if isinstance(front_matter, dict) else None

        except Exception as e:
            logger.warning(f"Failed to parse front matter from {file_path}: {e}")
            return None
