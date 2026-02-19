# Generated manually for feedback app

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FeedbackBeacon',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.SlugField(max_length=64, unique=True)),
                ('title', models.CharField(max_length=120)),
                ('body_markdown', models.TextField(blank=True, default='')),
                ('feature_context', models.TextField(blank=True, default='')),
                ('scope', models.CharField(choices=[('global', 'Global'), ('route', 'Route'), ('component', 'Component')], default='global', max_length=16)),
                ('route_pattern', models.CharField(blank=True, default='', max_length=255)),
                ('is_active', models.BooleanField(default=True)),
                ('start_at', models.DateTimeField(blank=True, null=True)),
                ('end_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='FeedbackItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('bug', 'Bug'), ('request', 'Request'), ('idea', 'Idea')], max_length=16)),
                ('message', models.TextField()),
                ('page_url', models.TextField(blank=True, default='')),
                ('status', models.CharField(choices=[('new', 'New'), ('triaged', 'Triaged'), ('planned', 'Planned'), ('shipped', 'Shipped'), ('wontfix', "Won't Fix")], default='new', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('beacon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='feedback.feedbackbeacon')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
