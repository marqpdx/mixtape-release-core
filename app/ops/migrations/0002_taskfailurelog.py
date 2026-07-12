from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskFailureLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task_name", models.CharField(db_index=True, max_length=256)),
                ("exception_type", models.CharField(max_length=256)),
                ("exception_message", models.TextField(blank=True)),
                ("traceback", models.TextField(blank=True)),
                ("queue", models.CharField(blank=True, default="", max_length=128)),
                ("retries", models.IntegerField(default=0)),
                ("failed_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "verbose_name": "Task Failure",
                "verbose_name_plural": "Task Failures",
                "ordering": ["-failed_at"],
            },
        ),
    ]
