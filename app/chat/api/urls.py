# chat/api/urls.py

from django.urls import path

from . import views


# parent path /api/chat/

urlpatterns = [
    path("conversations", views.conversation_list_create, name="conversation-list-create"),

    path("conversations/unreads", views.UnreadsListView.as_view(), name="chat-unreads"),
    path("conversations/search", views.search_conversations), # new, not yet implemented
    path("conversations/status", views.ConversationStatusTrackerListView.as_view(), name="conversation-status-list"),

    path("conversations/<slug:slug>", views.conversation_detail, name="conversation-detail"),
    path("conversations/<slug:slug>/messages", views.conversation_messages, name="conversation-messages"),
    path("conversations/<slug:slug>/status", views.ConversationStatusTrackerDetail.as_view(), name="conversation-status"),
    path("conversations/<slug:slug>/read", views.ConversationReadView.as_view()),
    path("conversations/<slug:slug>/voice-upload", views.conversation_voice_upload, name="conversation-voice-upload"),
    path("conversations/<slug:slug>/retention", views.conversation_retention, name="conversation-retention"),

    path("messages/<uuid:pk>/react", views.ChatMessageViewSet.as_view({"post": "react"}), name="message-react"),
    path("mention-autocomplete", views.mention_autocomplete, name="mention-autocomplete"),
]
