# initiatives/api/urls.py
# No trailing slashes — follows project convention.

from django.urls import path

from . import views

# ---------------------------------------------------------------------------
# Aperture-log endpoints — included at api/initiatives/
# ---------------------------------------------------------------------------

aperture_patterns = [
    path("search", views.ApertureInitiativeTypeaheadView.as_view(), name="initiative-search"),
    path("personal", views.PersonalInitiativeCreateView.as_view(), name="initiative-personal-create"),
    path("<uuid:initiative_id>/aperture-log", views.ApertureLogView.as_view(), name="aperture-log"),
    path("<uuid:initiative_id>/aperture-log/entries", views.ApertureLogEntryCreateView.as_view(), name="aperture-log-entries"),
    path("<uuid:initiative_id>/aperture-log/entries/<uuid:entry_id>", views.ApertureLogEntryDetailView.as_view(), name="aperture-log-entry-detail"),
    path("<uuid:initiative_id>/aperture-log/handoffs", views.ApertureLogHandoffsView.as_view(), name="aperture-log-handoffs"),
    path("<uuid:initiative_id>/aperture-log/handover-draft", views.ApertureLogHandoverDraftView.as_view(), name="aperture-log-handover-draft"),
]

action_run_patterns = [
    path("action-runs", views.ActionRunListCreateView.as_view(), name="action-run-create"),
    path("action-runs/<uuid:action_run_id>", views.ActionRunDetailView.as_view(), name="action-run-detail"),
    path("action-runs/<uuid:action_run_id>/approve", views.ActionRunApproveView.as_view(), name="action-run-approve"),
]

agent_object_patterns = [
    path("notes", views.NoteListCreateView.as_view(), name="initiative-note-create"),
    path("notes/<uuid:note_id>", views.NoteDetailView.as_view(), name="initiative-note-detail"),
    path("reminders", views.ReminderListCreateView.as_view(), name="initiative-reminder-create"),
    path("reminders/<uuid:reminder_id>", views.ReminderDetailView.as_view(), name="initiative-reminder-detail"),
    path("tasks", views.TaskListCreateView.as_view(), name="initiative-task-create"),
    path("tasks/<uuid:task_id>", views.TaskDetailView.as_view(), name="initiative-task-detail"),
]

mobile_command_patterns = [
    path("mobile/commands", views.MobileCommandListCreateView.as_view(), name="initiative-mobile-command-create"),
    path("mobile/commands/<uuid:command_id>", views.MobileCommandDetailView.as_view(), name="initiative-mobile-command-detail"),
    path("mobile/commands/<uuid:command_id>/confirm", views.MobileCommandConfirmView.as_view(), name="initiative-mobile-command-confirm"),
    path("mobile/transcribe", views.MobileTranscribeUploadView.as_view(), name="initiative-mobile-transcribe-upload"),
    path("mobile/transcribe/<uuid:job_id>", views.MobileTranscribeStatusView.as_view(), name="initiative-mobile-transcribe-status"),
]

# ---------------------------------------------------------------------------
# Group-scoped initiative patterns — included under api/groups/<slug>/initiatives/
# ---------------------------------------------------------------------------

# Base path when group-scoped: api/groups/<slug>/initiatives/
# Included in groups/api/urls.py as:
#   path("<slug:slug>/initiatives/", include(group_initiatives_patterns))

worktable_group_patterns = [
    path("<slug:slug>/reminders", views.GroupReminderListView.as_view(), name="group-reminder-list"),
    path("<slug:slug>/tasks", views.GroupTaskListView.as_view(), name="group-task-list"),
]

group_initiatives_patterns = [
    # Initiative CRUD
    path("", views.InitiativeListCreateView.as_view(), name="initiative-list-create"),
    path("<uuid:initiative_id>", views.InitiativeDetailView.as_view(), name="initiative-detail"),

    # Rolling summary
    path("<uuid:initiative_id>/rolling-summary", views.RollingSummaryView.as_view(), name="initiative-rolling-summary"),

    # Sessions
    path("<uuid:initiative_id>/sessions", views.SessionListCreateView.as_view(), name="initiative-session-list-create"),
    path("<uuid:initiative_id>/sessions/<uuid:session_id>", views.SessionDetailView.as_view(), name="initiative-session-detail"),

    # Session exchange (AI streaming — stub in v0)
    path("<uuid:initiative_id>/sessions/<uuid:session_id>/exchange", views.SessionExchangeView.as_view(), name="initiative-session-exchange"),

    # Distillation
    path("<uuid:initiative_id>/sessions/<uuid:session_id>/propose-distillation", views.ProposeDistillationView.as_view(), name="initiative-session-propose-distillation"),
    path("<uuid:initiative_id>/sessions/<uuid:session_id>/commit-distillation", views.CommitDistillationView.as_view(), name="initiative-session-commit-distillation"),

    # Artifacts
    path("<uuid:initiative_id>/artifacts", views.ArtifactListCreateView.as_view(), name="initiative-artifact-list-create"),
    path("<uuid:initiative_id>/artifacts/<uuid:artifact_id>", views.ArtifactDetailView.as_view(), name="initiative-artifact-detail"),
    path("<uuid:initiative_id>/artifacts/<uuid:artifact_id>/route-to-puddlejump", views.ArtifactRouteToPuddlejumpView.as_view(), name="initiative-artifact-route-puddlejump"),

    # Linked outputs
    path("<uuid:initiative_id>/linked-outputs", views.LinkedOutputListCreateView.as_view(), name="initiative-linked-output-list-create"),

    # Session import (two-stage: preview → confirm)
    path("<uuid:initiative_id>/import-session/preview", views.ImportSessionPreviewView.as_view(), name="initiative-import-session-preview"),
    path("<uuid:initiative_id>/import-session/confirm", views.ImportSessionConfirmView.as_view(), name="initiative-import-session-confirm"),
]
