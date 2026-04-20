from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View

from .models import ProspectIntakeSession, ProspectQuestion


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
        if session.status == "submitted":
            from django.shortcuts import redirect
            return redirect("intake-submitted", token=token)
        questions = ProspectQuestion.objects.filter(is_active=True).order_by("order_index")
        existing = {str(r.question_id): r.response_text for r in session.responses.all()}
        return render(request, "prospects/intake_questions.html", {
            "session": session,
            "questions": questions,
            "existing_responses": existing,
            "token": str(token),
        })


class IntakeSubmittedView(View):
    def get(self, request, token):
        session = get_object_or_404(ProspectIntakeSession, resume_token=token)
        return render(request, "prospects/intake_submitted.html", {"session": session})
