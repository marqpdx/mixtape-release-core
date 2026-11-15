"""Open an empty Folio Dictionary for one named Folio, as its author.

    python manage.py open_folio_dictionary <folio-uuid> --author <username>

Changes one row: sets Folio.dictionary_revision to 0 and adds one to its
context_revision. Running it again changes nothing. It enables no flag.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from folio.dictionary.commands import open_dictionary
from heddle.errors import InterpretationError


class Command(BaseCommand):
    help = "Open an empty Folio Dictionary for one Folio, as its author."

    def add_arguments(self, parser):
        parser.add_argument("folio_id")
        parser.add_argument("--author", required=True, help="Username of the Folio's own author.")

    def handle(self, *args, folio_id, author, **options):
        user = get_user_model().objects.filter(username=author, is_active=True).first()
        if user is None:
            raise CommandError("No active member has that username.")
        try:
            result = open_dictionary(author=user, folio_id=folio_id)
        except (InterpretationError, ValidationError, ValueError, TypeError):
            raise CommandError("That member has no such Folio.") from None
        state = "Opened an empty Dictionary" if result["opened"] else "Already open; nothing changed"
        self.stdout.write(f"{state}: Folio {result['folio_id']}, Dictionary revision "
                          f"{result['dictionary_revision']}, context revision {result['context_revision']}.")
