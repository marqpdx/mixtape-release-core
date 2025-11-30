# tasks/cleanup.py

from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

@shared_task
def cleanup_empty_drafts():
    """
    Clean up empty draft pieces that are older than 24 hours.
    Run this task daily via Celery Beat.
    """
    from writing.models import WritingPiece  # Replace with actual import

    # Calculate cutoff time (24 hours ago)
    cutoff_time = timezone.now() - timedelta(hours=24)

    try:
        with transaction.atomic():
            # Find empty drafts older than 24 hours
            empty_drafts = WritingPiece.objects.filter(
                is_empty=True,
                status='draft',
                created_at__lt=cutoff_time
            )

            count = empty_drafts.count()
            logger.info(f"Found {count} empty drafts to clean up")

            if count > 0:
                # Also delete any associated working copies
                piece_ids = list(empty_drafts.values_list('id', flat=True))

                # Delete working copies first (if you have a separate model)
                # WorkingCopy.objects.filter(piece_id__in=piece_ids).delete()

                # Delete the empty pieces
                deleted_count = empty_drafts.delete()[0]

                logger.info(f"Successfully deleted {deleted_count} empty drafts")
                return {
                    'status': 'success',
                    'deleted_count': deleted_count,
                    'piece_ids': piece_ids
                }
            else:
                logger.info("No empty drafts found for cleanup")
                return {
                    'status': 'success',
                    'deleted_count': 0,
                    'piece_ids': []
                }

    except Exception as e:
        logger.error(f"Error during empty draft cleanup: {str(e)}")
        return {
            'status': 'error',
            'error': str(e)
        }

@shared_task
def cleanup_old_working_copies():
    """
    Clean up working copies for deleted pieces or very old working copies.
    Run this task weekly.
    """
    from django.db.models import Q
    from writing.models import WorkingCopy, WritingPiece  # Replace with actual imports

    cutoff_time = timezone.now() - timedelta(days=7)

    try:
        with transaction.atomic():
            # Find working copies for non-existent pieces or very old ones
            orphaned_working_copies = WorkingCopy.objects.filter(
                Q(piece__isnull=True) |
                Q(updated_at__lt=cutoff_time)
            )

            count = orphaned_working_copies.count()
            deleted_count = orphaned_working_copies.delete()[0]

            logger.info(f"Cleaned up {deleted_count} orphaned working copies")
            return {
                'status': 'success',
                'deleted_count': deleted_count
            }

    except Exception as e:
        logger.error(f"Error during working copy cleanup: {str(e)}")
        return {
            'status': 'error',
            'error': str(e)
        }