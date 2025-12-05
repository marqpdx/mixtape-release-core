def send_transactional_email(
    subject,
    to_emails,
    template_base,
    context,
    from_email=None,
    cc_emails=None,
    bcc_emails=None,
    reply_to=None,
):
    """
    Send a transactional email (text and HTML) using Django templates.

    template_base → e.g. "emails/invite_to_group"
    Looks for:
      - <template_base>.txt
      - <template_base>.html
    """

    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    text_body = render_to_string(f"{template_base}.txt", context)
    html_body = render_to_string(f"{template_base}.html", context)

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=to_emails,
        cc=cc_emails,
        bcc=bcc_emails,
        reply_to=[reply_to] if reply_to else None,
    )
    email.attach_alternative(html_body, "text/html")
    email.send()
