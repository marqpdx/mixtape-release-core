"""
Management command to create the Puddlejump OAuth2 application.

Usage:
    python manage.py setup_puddlejump_oauth

This creates a public OAuth2 application for the Puddlejump desktop sync client.
The application uses PKCE for security (no client secret needed).
"""

from django.core.management.base import BaseCommand
from oauth2_provider.models import Application


class Command(BaseCommand):
    help = "Create the Puddlejump OAuth2 application for desktop sync"

    def handle(self, *args, **options):
        # Check if application already exists
        app, created = Application.objects.get_or_create(
            client_id="puddlejump-desktop",
            defaults={
                "name": "Puddlejump Desktop",
                "client_type": Application.CLIENT_PUBLIC,  # Desktop app, no secret
                "authorization_grant_type": Application.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "puddlejump://callback\nhttp://localhost:5173/callback",
                "skip_authorization": False,  # User must approve first time
            }
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created Puddlejump OAuth application:\n"
                    f"  Client ID: {app.client_id}\n"
                    f"  Grant Type: Authorization Code\n"
                    f"  Client Type: Public (PKCE required)\n"
                    f"  Redirect URIs:\n"
                    f"    - puddlejump://callback (production)\n"
                    f"    - http://localhost:5173/callback (development)"
                )
            )
        else:
            # Update redirect URIs in case they changed
            app.redirect_uris = "puddlejump://callback\nhttp://localhost:5173/callback"
            app.save()
            self.stdout.write(
                self.style.WARNING(
                    f"Puddlejump OAuth application already exists (client_id: {app.client_id}). "
                    f"Updated redirect URIs."
                )
            )

        self.stdout.write("\nOAuth2 endpoints:")
        self.stdout.write("  Authorize: /oauth/authorize/")
        self.stdout.write("  Token:     /oauth/token/")
        self.stdout.write("  Revoke:    /oauth/revoke_token/")
