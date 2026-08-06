# utils/email/mailjet_client.py
"""
Thin Mailjet HTTP API wrapper for transactional sends.

Encapsulates client init, from-address parsing, payload construction, and
response handling so individual Celery tasks don't each re-implement them.
Returns the provider_message_id on success; raises MailjetSendError on failure.
"""

import re


class MailjetSendError(Exception):
    pass


def send_via_mailjet(
    *,
    to_email: str,
    to_name: str = "",
    subject: str,
    text_body: str,
    html_body: str,
    custom_id: str = "",
) -> str:
    """
    Send a single transactional email via the Mailjet HTTP API.
    Returns the provider MessageID string, or "" if the API doesn't provide one.
    Raises MailjetSendError on any delivery failure.
    """
    from django.conf import settings
    from mailjet_rest import Client

    from_email, from_name = _parse_from_address(settings.DEFAULT_FROM_EMAIL)

    mailjet = Client(
        auth=(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD),
        version="v3.1",
    )

    to_recipient = {"Email": to_email}
    if to_name:
        to_recipient["Name"] = to_name

    payload = {
        "Messages": [
            {
                "From": {"Email": from_email, "Name": from_name},
                "To": [to_recipient],
                "Subject": subject,
                "TextPart": text_body,
                "HTMLPart": html_body,
            }
        ]
    }
    if custom_id:
        payload["Messages"][0]["CustomID"] = custom_id

    try:
        response = mailjet.send.create(data=payload)
    except Exception as exc:
        raise MailjetSendError(f"Mailjet request error: {exc}") from exc

    status_code = response.status_code
    response_json = response.json()

    if status_code != 200:
        raise MailjetSendError(f"Mailjet HTTP {status_code}: {response_json}")

    try:
        message_result = response_json["Messages"][0]
        if message_result.get("Status") != "success":
            raise MailjetSendError(f"Mailjet message status not success: {message_result}")
        return str(message_result["To"][0]["MessageID"])
    except (KeyError, IndexError, TypeError):
        return ""


def _parse_from_address(from_email_setting: str) -> tuple[str, str]:
    """Parse 'Display Name <email@domain.com>' → (email, name). Falls back to (raw, "")."""
    match = re.match(r"^(.+?)\s*<(.+?)>\s*$", from_email_setting)
    if match:
        return match.group(2), match.group(1).strip()
    return from_email_setting, ""
