# assets/tasks/__init__.py

# Import and re-export all tasks
from .cleanup import delete_image_async
from .upload import upload_group_asset_task

__all__ = ['delete_image_async', 'upload_group_asset_task']
