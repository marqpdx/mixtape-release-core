from django.db import migrations


class Migration(migrations.Migration):
    """
    Removes Group.crossroads_enabled — deprecated per FN-0010 FN-D20.

    The field was designed for a feature-stripped tenant type (Catalyst-only,
    two routes) that was never built. Product direction moved to one integrated
    environment; the field was never read in any view or permission check.
    See field-notes/FN10/10-FieldNote-tenant-enforcement-architecture-0.2.3.md.
    """

    dependencies = [
        ("groups", "0028_add_page_component"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="group",
            name="crossroads_enabled",
        ),
    ]
