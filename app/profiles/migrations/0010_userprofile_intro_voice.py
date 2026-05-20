from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0009_profile_community_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='intro_voice',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Storage key for intro voice note audio file.',
                max_length=512,
            ),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='intro_voice_transcript',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Auto-generated transcript of intro voice note.',
            ),
        ),
    ]
