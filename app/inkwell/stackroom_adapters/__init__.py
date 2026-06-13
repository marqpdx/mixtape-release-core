from .seed import SeedAdapter
from .leaf import LeafAdapter
from .working_document import WorkingDocumentAdapter
from .writing_piece import WritingPieceAdapter
from .user_profile import UserProfileAdapter
from .threadworks_discussion import ThreadworksDiscussionAdapter
from .almanac_event import AlmanacEventAdapter

ADAPTER_REGISTRY = [
    SeedAdapter(),
    LeafAdapter(),
    WorkingDocumentAdapter(),
    WritingPieceAdapter(),
    UserProfileAdapter(),
    ThreadworksDiscussionAdapter(),
    AlmanacEventAdapter(),
]


def get_adapter(obj):
    for adapter in ADAPTER_REGISTRY:
        if adapter.supports(obj):
            return adapter
    raise ValueError(f"No Stackroom adapter for {type(obj).__name__}")
