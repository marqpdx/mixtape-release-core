import json

from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View

from .models import ProspectIntakeSession, ProspectQuestion, ProspectResponse


def _get_session_or_410(token):
    session = get_object_or_404(ProspectIntakeSession, resume_token=token)
    if session.token_expires_at and session.token_expires_at < timezone.now():
        return None, True
    return session, False


class IntakeWelcomeView(View):
    def get(self, request, token):
        session = get_object_or_404(ProspectIntakeSession, resume_token=token)
        if session.token_expires_at and session.token_expires_at < timezone.now():
            return render(request, "prospects/intake_expired.html", status=410)
        return render(request, "prospects/intake_welcome.html", {"session": session})


class IntakeQuestionsView(View):
    def get(self, request, token):
        session = get_object_or_404(ProspectIntakeSession, resume_token=token)
        if session.token_expires_at and session.token_expires_at < timezone.now():
            return render(request, "prospects/intake_expired.html", status=410)
        submitted = session.status == "submitted"
        questions = ProspectQuestion.objects.filter(is_active=True).order_by("order_index")
        all_responses = session.responses.select_related("question").all()
        typed = {str(r.question_id): r.response_text for r in all_responses if r.kind == "typed"}
        files = []
        for r in all_responses:
            if r.kind == "file":
                files.append({
                    "id": str(r.id),
                    "question_id": str(r.question_id),
                    "file_name": r.source_file.name.split("/")[-1] if r.source_file else "Attached file",
                    "processing_status": r.processing_status,
                    "response_text": r.response_text,
                })
            elif r.kind == "voice":
                files.append({
                    "id": str(r.id),
                    "question_id": str(r.question_id),
                    "file_name": r.audio_file.name.split("/")[-1] if r.audio_file else "Voice note",
                    "processing_status": r.processing_status,
                    "response_text": r.response_text,
                })
        return render(request, "prospects/intake_questions.html", {
            "session": session,
            "questions": questions,
            "existing_responses_json": json.dumps(typed),
            "existing_files_json": json.dumps(files),
            "token": str(token),
            "submitted": submitted,
        })


class IntakeSubmittedView(View):
    def get(self, request, token):
        session = get_object_or_404(ProspectIntakeSession, resume_token=token)
        return render(request, "prospects/intake_submitted.html", {"session": session})
