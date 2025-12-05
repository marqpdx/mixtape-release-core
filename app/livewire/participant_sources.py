# apps/livewire/participant_sources.py
from django.contrib.auth import get_user_model


User = get_user_model()

REGISTRY = {}  # model class -> callable(anchor_obj) -> Iterable[User]


def register(model_cls):
    """Decorator: register a participant source for a given model class."""
    def _wrap(func):
        REGISTRY[model_cls] = func
        return func
    return _wrap


def users_for_anchor(anchor_obj) -> set[int]:
    """
    Return a set of user IDs who should be participants for this anchor.
    """
    # exact class match first
    fn = REGISTRY.get(anchor_obj.__class__)
    if fn:
        return {u.id for u in fn(anchor_obj)}

    # duck-typed fallbacks
    # Common patterns: anchor.members, anchor.get_members(), anchor.get_member_users()
    for attr in ("members", "get_members", "get_member_users"):
        if hasattr(anchor_obj, attr):
            value = getattr(anchor_obj, attr)
            users = value() if callable(value) else value
            try:
                return {u.id for u in users.all()}  # queryset path
            except AttributeError:
                return {u.id for u in users}       # iterable path

    return set()
