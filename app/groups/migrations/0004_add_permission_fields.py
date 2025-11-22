# Generated migration for Phase 1: Permissions System
# Adds decorator and additional_permissions fields for new permissions infrastructure

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('groups', '0003_remove_group_author_remove_group_author_name_and_more'),
    ]

    operations = [
        # Add decorators field to Group
        # Stores semantic capability bundles (e.g., ["education_hub", "event_venue"])
        migrations.AddField(
            model_name='group',
            name='decorators',
            field=models.JSONField(
                default=list,
                blank=True,
                help_text="Semantic capability bundles applied to this group (e.g., education_hub, event_venue)"
            ),
        ),

        # Add additional_permissions field to Group (for Phase 4)
        # Allows direct permission grants as escape hatch
        migrations.AddField(
            model_name='group',
            name='additional_permissions',
            field=models.JSONField(
                default=list,
                blank=True,
                help_text="Direct permission grants for edge cases (use sparingly)"
            ),
        ),

        # Add decorators field to GroupMembership
        # Stores member-specific semantic decorators (e.g., ["moderator"])
        migrations.AddField(
            model_name='groupmembership',
            name='decorators',
            field=models.JSONField(
                default=list,
                blank=True,
                help_text="Semantic decorators applied to this membership (e.g., moderator)"
            ),
        ),

        # Add additional_permissions field to GroupMembership (for Phase 4)
        # Allows direct permission grants to individual members
        migrations.AddField(
            model_name='groupmembership',
            name='additional_permissions',
            field=models.JSONField(
                default=list,
                blank=True,
                help_text="Direct permission grants for this member (use sparingly)"
            ),
        ),

        # Add indexes for performance
        migrations.AddIndex(
            model_name='group',
            index=models.Index(fields=['is_active'], name='groups_group_is_active_idx'),
        ),
        migrations.AddIndex(
            model_name='groupmembership',
            index=models.Index(fields=['is_active', 'is_pending'], name='groups_membership_active_pending_idx'),
        ),
    ]
