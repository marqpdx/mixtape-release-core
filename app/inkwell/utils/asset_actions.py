# ai/utils/asset_actions.py

import logging


logger = logging.getLogger(__name__)


from inkwell.models import SuggestedAsset
from inkwell.tasks.synopsis import generate_synopsis_task


def preapprove_asset(asset: SuggestedAsset, trigger_synopsis=True):
    if asset.approved:
        return

    asset.approved = True
    asset.save()

    # if trigger_synopsis and settings.DJANGO_ENV == 'prod':
    if True:
        logger.info(" Triggering synopsis for asset: %s", asset.id)
        generate_synopsis_task.delay(asset.id)
    else:
        logger.warning(" Skipping synopsis for asset %s", asset.id)
