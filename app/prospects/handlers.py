from django.conf import settings
from django.core.mail import send_mail
from django.dispatch import receiver

from .signals import intake_submitted


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
