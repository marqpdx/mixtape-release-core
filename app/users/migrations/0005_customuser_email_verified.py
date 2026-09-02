from django.db import migrations, models


def backfill_email_verified(apps, schema_editor):
    """
    All existing active accounts were created via the invite flow and have
    implicit email verification. Mark them verified so existing users are
    not affected by the gate.
    """
    CustomUser = apps.get_model("users", "CustomUser")
    CustomUser.objects.filter(is_active=True).update(email_verified=True)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_stackroom_library_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="email_verified",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "True when the user has proven inbox control. Set automatically on invite "
                    "acceptance; requires explicit verification link for open-registration accounts."
                ),
            ),
        ),
        migrations.RunPython(backfill_email_verified, migrations.RunPython.noop),
    ]
