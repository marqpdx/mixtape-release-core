# utils/tasks/send_transactional_email_task.py

import traceback

from celery import shared_task
from django.utils import timezone as dj_timezone


print("[celery] 📬 send_transactional_email_task.py has been loaded")





@shared_task(
    name="utils.tasks.send_transactional_email_task",
    bind=True,
    max_retries=0,
    # default_retry_delay=60
)
def send_transactional_email_task(
    self,
    subject,
    to_emails,
    template_base,
    context,
    invitation_id=None,
    from_email=None,
    cc_emails=None,
    bcc_emails=None,
    reply_to=None,
):
    """
    Celery task to send a transactional email using Django templates.

    template_base → e.g. "email/invite_to_group"
    Looks for:
        - templates/email/invite_to_group.txt
        - templates/email/invite_to_group.html
    """
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    from groups.models import EmailStatus

    def debug_ts(message: str) -> None:
        print(f"[{dj_timezone.now().isoformat()}] {message}")


    debug_ts("[celery] 📬 ENTER send_transactional_email_task.py has been loaded (now in send_transactional_email_task)")


    try:

        text_body = render_to_string(f"{template_base}.txt", context)
        html_body = render_to_string(f"{template_base}.html", context)

        debug_ts("[celery] 📬 send_transactional_email_task.py before email =")

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=to_emails,
            cc=cc_emails,
            bcc=bcc_emails,
            reply_to=[reply_to] if reply_to else None,
        )
        email.attach_alternative(html_body, "text/html")

        debug_ts("[celery] 📬 send_transactional_email_task.py after attach")


        email.send()

        # Optional: update invitation
        if invitation_id:
            debug_ts(f"[celery] Updating invitation {invitation_id} to SENT status")
            from groups.models import GroupInvitation
            try:
                invitation = GroupInvitation.objects.get(id=invitation_id)
                debug_ts(f"[celery] Found invitation {invitation_id}, current status: {invitation.email_status}")
                # Mark as sent after successful email delivery
                invitation.email_status = EmailStatus.SENT
                invitation.save()
                debug_ts(f"[celery] Successfully updated invitation {invitation_id} to SENT")
            except GroupInvitation.DoesNotExist:
                # Log, but don't crash
                debug_ts(f"[celery] ERROR: Invitation with id {invitation_id} does not exist.")
            except Exception as e:
                debug_ts(f"[celery] ERROR: Failed to update invitation {invitation_id}: {type(e).__name__}: {e}")


    except Exception as e:
        debug_ts(f"[celery] ERROR in send_transactional_email_task: {type(e).__name__}: {e}")
        traceback.print_exc()
        # For now, just fail fast so we can see the error
        raise
        # once fixed, you can go back to retrying if you want
        # raise self.retry(exc=e)

    # except Exception as e:
    #     # Mark as failed
    #     if invitation_id:
    #         from groups.models import GroupInvitation
    #         invitation = GroupInvitation.objects.filter(id=invitation_id).first()
    #         if invitation:
    #             invitation.email_status = EmailStatus.FAILED
    #             invitation.save()

    #     raise self.retry(exc=e)
