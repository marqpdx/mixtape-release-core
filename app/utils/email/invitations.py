# utils/email/invitations.py

from django.utils.text import slugify

from users.models import CustomUser


# TODO Add this to the view that calls it, we don't need this function here.

# def send_group_invitation_email(invited_email, group, invited_by, message="", invite_url=None, token=None):
#     """
#     Send a group invitation email and create a GroupInvitation record.
#     """

#     # context = {
#     #     "group": group,
#     #     "invited_by": invited_by,
#     #     "message": message,
#     #     "invite_url": invite_url,
#     # }

#     # subject = f"You're invited to join {group.name} on Mixtape"
#     # text_body = render_to_string("emails/invite_to_group.txt", context)
#     # html_body = render_to_string("emails/invite_to_group.html", context)

#     # 6. Send email
#     # This works! We are deprecating this in favor of the code that follows.
#     # msg = EmailMultiAlternatives(
#     #     subject=subject,
#     #     body=text_body,
#     #     from_email=settings.DEFAULT_FROM_EMAIL,
#     #     to=[invited_email],
#     # )
#     # msg.attach_alternative(html_body, "text/html")
#     # msg.send()

#     send_transactional_email(
#         subject=subject,
#         to_emails=[invited_email],
#         template_base="email/invite_to_group",
#         context=context,
#     )




def generate_username_from_email(email: str) -> str:
    """
    Generates a slug-style username based on the email prefix.
    Ensures uniqueness by appending a number if needed.
    """
    base = slugify(email.split("@")[0])
    username = base
    counter = 1

    while CustomUser.objects.filter(username=username).exists():
        counter += 1
        username = f"{base}{counter}"

    return username






# def send_group_invitation_email(invited_email, group, invited_by, message="", invite_url=None):
#     """Send a group invitation email to a user (existing or not)."""
#     token = get_random_string(48)

#     # Create DB record
#     invitation = GroupInvitation.objects.create(
#         invited_email=invited_email,
#         invited_by=invited_by,
#         group=group,
#         message=message,
#         token=token,
#     )

#     # Compose email
#     subject = f"You're invited to join {group.name} on Mixtape"
#     context = {
#         "group": group,
#         "invitation": invitation,
#         "inviter": invited_by,
#         "message": message,
#         "accept_url": f"{settings.FRONTEND_URL}/invite/accept/{token}/",
#         "invite_url": invite_url,
#     }

#     html_body = render_to_string("emails/invite_to_group.html", context)
#     text_body = render_to_string("emails/invite_to_group.txt", context)

#     msg = EmailMultiAlternatives(
#         subject=subject,
#         body=text_body,
#         from_email=settings.DEFAULT_FROM_EMAIL,
#         to=[invited_email],
#     )
#     msg.attach_alternative(html_body, "text/html")
#     msg.send()

#     return invitation





