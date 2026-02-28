from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('feedback', '0002_alter_feedbackbeacon_id_alter_feedbackitem_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='feedbackitem',
            name='kind',
            field=models.CharField(
                choices=[('bug', 'Bug'), ('request', 'Request'), ('idea', 'Idea'), ('issue', 'Issue')],
                max_length=16,
            ),
        ),
    ]
