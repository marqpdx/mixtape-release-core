from django.conf import settings
from django.core.mail import send_mail
from django.dispatch import receiver

from .signals import intake_submitted, prospect_converted


@receiver(intake_submitted)
def notify_on_intake_submit(sender, intake_session, **kwargs):
    if not intake_session.notify_on_submit:
        return
    prospect = intake_session.prospect
    send_mail(
        subject=f"New intake submitted: {prospect.name}",
        message=f"Review: /prospects/{prospect.slug}/sessions/{intake_session.id}/",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[settings.PROSPECTS_NOTIFY_EMAIL],
        fail_silently=True,
    )


@receiver(prospect_converted)
def create_welcome_email_draft(sender, prospect, group, **kwargs):
    """
    Creates a WelcomeEmailDraft when a prospect converts to a client group.
    The draft sits in review until an operator edits and sends it manually.
    """
    from lanternmail.models import WelcomeEmailDraft

    to_name = prospect.primary_contact_name or prospect.name
    to_email = prospect.primary_contact_email
    if not to_email:
        return  # No email address — nothing to draft

    subject = f"Welcome to Mixtape — {group.title}"

    body = f"""Hi {to_name},

We're delighted to have {prospect.name} on board as a Mixtape client.

Your group — {group.title} — has been set up and your intake answers have been brought over to seed your group context. A few things are ready for you:

- Your group is live at: /group/{group.slug}/
- Your context profile has been initialized from your intake responses. We recommend reviewing it and filling in any gaps when you have a moment.
- Your team can start capturing operational notes (fixes, reminders, supply needs) right away from the Capture tab.

We'll follow up shortly to walk you through next steps. In the meantime, don't hesitate to reach out with any questions.

Looking forward to working together.

---
[Review and edit this draft before sending]
"""

    WelcomeEmailDraft.objects.get_or_create(
        prospect=prospect,
        group=group,
        defaults={
            "to_name": to_name,
            "to_email": to_email,
            "subject": subject,
            "body": body.strip(),
        },
    )
