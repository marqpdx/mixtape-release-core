from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sourcework", "0006_externalconnection_unique_account_per_group"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="externalconnection",
            constraint=models.UniqueConstraint(
                fields=["group", "provider", "provider_account_id"],
                condition=~models.Q(provider_account_id=""),
                name="unique_connected_account_per_group_provider",
            ),
        ),
    ]
