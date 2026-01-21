# Generated manually for coalition invitations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("groups", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="groupinvitation",
            name="invited_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="group_invitations_received",
                to="groups.group",
            ),
        ),
        migrations.AddField(
            model_name="groupinvitation",
            name="invitation_kind",
            field=models.CharField(
                choices=[("invite", "Invite"), ("request", "Request")],
                default="invite",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="groupinvitation",
            name="invited_email",
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
    ]
