# switchboard/api/urls.py

from django.urls import path

from .views import (
    agent_add_proxy,
    agent_note_proxy,
    agent_parse_proxy,
    agent_reminder_proxy,
    agent_task_proxy,
    classify_async_proxy,
    context_shape_async_proxy,
    draft_async_proxy,
    refine_async_proxy,
    summarize_async_proxy,
    think_cluster_async_proxy,
)

urlpatterns = [
    path("summarize/async", summarize_async_proxy, name="switchboard-summarize-async"),
    path("classify/async", classify_async_proxy, name="switchboard-classify-async"),
    path("context-shape/async", context_shape_async_proxy, name="switchboard-context-shape-async"),
    path("draft/async", draft_async_proxy, name="switchboard-draft-async"),
    path("refine/async", refine_async_proxy, name="switchboard-refine-async"),
    path("think/cluster", think_cluster_async_proxy, name="switchboard-think-cluster"),
    path("agent/parse", agent_parse_proxy, name="switchboard-agent-parse"),
    path("agent/add", agent_add_proxy, name="switchboard-agent-add"),
    path("agent/note", agent_note_proxy, name="switchboard-agent-note"),
    path("agent/remind", agent_reminder_proxy, name="switchboard-agent-remind"),
    path("agent/task", agent_task_proxy, name="switchboard-agent-task"),
]
