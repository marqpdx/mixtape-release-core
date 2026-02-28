from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feedback", "0003_alter_feedbackitem_kind"),
    ]

    operations = [
        migrations.AlterField(
            model_name="feedbackitem",
            name="status",
            field=models.CharField(
                choices=[
                    ("new", "New"),
                    ("sent_to_agent", "Sent To Agent"),
                    ("triaged", "Triaged"),
                    ("planned", "Planned"),
                    ("shipped", "Shipped"),
                    ("wontfix", "Won't Fix"),
                ],
                default="new",
                max_length=16,
            ),
        ),
    ]
