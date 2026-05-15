from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0007_userprofile_preferences'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProfileTheme',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('theme', models.CharField(choices=[('paper', 'Paper'), ('noir', 'Noir'), ('garden', 'Garden'), ('neon', 'Neon'), ('sunset', 'Sunset')], default='paper', max_length=16)),
                ('accent', models.CharField(default='#c2410c', max_length=7)),
                ('font', models.CharField(choices=[('editorial', 'Editorial'), ('modern', 'Modern'), ('mono', 'Mono'), ('playful', 'Playful')], default='editorial', max_length=16)),
                ('background', models.CharField(choices=[('none', 'None'), ('paper', 'Paper'), ('grid', 'Grid'), ('leaves', 'Leaves'), ('sunset', 'Sunset'), ('halftone', 'Halftone')], default='paper', max_length=16)),
                ('avatar_shape', models.CharField(choices=[('rounded', 'Rounded'), ('circle', 'Circle'), ('square', 'Square'), ('blob', 'Blob')], default='rounded', max_length=16)),
                ('density', models.CharField(choices=[('compact', 'Compact'), ('cozy', 'Cozy'), ('roomy', 'Roomy')], default='cozy', max_length=16)),
                ('decorations', models.BooleanField(default=True)),
                ('avatar_sticker', models.CharField(blank=True, max_length=4)),
                ('section_layout', models.JSONField(default=list)),
                ('version', models.PositiveIntegerField(default=1)),
                ('profile', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='theme_config', to='profiles.userprofile')),
            ],
            options={'app_label': 'profiles'},
        ),
        migrations.CreateModel(
            name='PinnedShowcase',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('tape', 'Tape'), ('project', 'Project'), ('quote', 'Quote')], default='tape', max_length=16)),
                ('label', models.CharField(blank=True, max_length=40)),
                ('title', models.CharField(blank=True, max_length=120)),
                ('subtitle', models.CharField(blank=True, max_length=200)),
                ('mark', models.CharField(blank=True, max_length=4)),
                ('cover', models.ImageField(blank=True, null=True, upload_to='pinned/')),
                ('cta_target', models.URLField(blank=True)),
                ('profile', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='pinned_showcase', to='profiles.userprofile')),
            ],
            options={'app_label': 'profiles'},
        ),
        migrations.CreateModel(
            name='PinnedTrack',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveSmallIntegerField()),
                ('label', models.CharField(blank=True, max_length=80)),
                ('name', models.CharField(max_length=140)),
                ('duration', models.CharField(blank=True, max_length=12)),
                ('showcase', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tracks', to='profiles.pinnedshowcase')),
            ],
            options={'app_label': 'profiles', 'ordering': ['position']},
        ),
        migrations.AddConstraint(
            model_name='pinnedtrack',
            constraint=models.UniqueConstraint(fields=['showcase', 'position'], name='unique_pinnedtrack_position'),
        ),
        migrations.CreateModel(
            name='NowPlaying',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('track', models.CharField(blank=True, max_length=140)),
                ('artist', models.CharField(blank=True, max_length=140)),
                ('label', models.CharField(blank=True, max_length=40)),
                ('source', models.CharField(blank=True, max_length=16)),
                ('source_id', models.CharField(blank=True, max_length=128)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('profile', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='now_playing', to='profiles.userprofile')),
            ],
            options={'app_label': 'profiles'},
        ),
        migrations.CreateModel(
            name='QAItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveSmallIntegerField()),
                ('q', models.CharField(max_length=30)),
                ('a', models.TextField(max_length=400)),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='qa_items', to='profiles.userprofile')),
            ],
            options={'app_label': 'profiles', 'ordering': ['position']},
        ),
        migrations.AddConstraint(
            model_name='qaitem',
            constraint=models.UniqueConstraint(fields=['profile', 'position'], name='unique_qaitem_position'),
        ),
        migrations.CreateModel(
            name='Badge',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('glyph', models.CharField(max_length=4)),
                ('text', models.CharField(max_length=40)),
                ('featured', models.BooleanField(default=False)),
                ('earned_at', models.DateTimeField(auto_now_add=True)),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='badges', to='profiles.userprofile')),
            ],
            options={'app_label': 'profiles'},
        ),
        migrations.AddConstraint(
            model_name='badge',
            constraint=models.UniqueConstraint(fields=['profile', 'glyph'], name='unique_badge_per_profile'),
        ),
        migrations.CreateModel(
            name='FeaturedLink',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveSmallIntegerField()),
                ('icon', models.CharField(choices=[('IG', 'Instagram'), ('SH', 'Shop'), ('NL', 'Newsletter'), ('PR', 'Patreon'), ('BC', 'Bandcamp'), ('SC', 'SoundCloud'), ('YT', 'YouTube'), ('EM', 'Email'), ('IT', 'itch.io'), ('BG', 'BoardGameGeek')], max_length=8)),
                ('title', models.CharField(max_length=40)),
                ('sub', models.CharField(blank=True, max_length=80)),
                ('url', models.URLField()),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='featured_links', to='profiles.userprofile')),
            ],
            options={'app_label': 'profiles', 'ordering': ['position']},
        ),
        migrations.AddConstraint(
            model_name='featuredlink',
            constraint=models.UniqueConstraint(fields=['profile', 'position'], name='unique_featuredlink_position'),
        ),
    ]
