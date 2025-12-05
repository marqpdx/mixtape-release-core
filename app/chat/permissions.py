# chat/permissions.py

from rest_framework.permissions import BasePermission

from .models import Conversation


class IsConversationParticipant(BasePermission):
    """
    Allows access only to users who participate in the conversation.
    Expects 'slug' in view.kwargs or 'conversation_id'/'conversation_slug' in request data/query.
    """

    message = "You are not a participant of this conversation."

    def _get_slug(self, request, view):
      return (getattr(view, "kwargs", {}) or {}).get("slug") \
          or request.data.get("conversation_slug") \
          or request.query_params.get("conversation_slug")

    def has_permission(self, request, view):
        slug = self._get_slug(request, view)
        if not slug:
            # Let has_object_permission handle object-level views that fetch instance by pk
            return True
        try:
            conv = Conversation.objects.get(slug=slug)
        except Conversation.DoesNotExist:
            return False
        return conv.participants.filter(id=request.user.id).exists()

    def has_object_permission(self, request, view, obj):
        # obj can be Conversation or Message with .conversation
        conv = obj if isinstance(obj, Conversation) else getattr(obj, "conversation", None)
        if not conv:
            return False
        return conv.participants.filter(id=request.user.id).exists()
