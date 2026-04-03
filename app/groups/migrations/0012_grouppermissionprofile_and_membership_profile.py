from django.db import migrations, models
import django.db.models.deletion


def seed_permission_profiles(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Group = apps.get_model("groups", "Group")
    GroupMembership = apps.get_model("groups", "GroupMembership")
    GroupPermissionProfile = apps.get_model("groups", "GroupPermissionProfile")
    GroupPermissionProfileItem = apps.get_model("groups", "GroupPermissionProfileItem")
    MembershipDecorator = apps.get_model("groups", "MembershipDecorator")
    MembershipHasDecorator = apps.get_model("groups", "MembershipHasDecorator")

    phase1 = {
        "can__ManageWriting": ("Manage Writing", "Create, edit, and manage writing pieces", "capability"),
        "can__ManageDispatch": ("Manage Dispatch", "Create, edit, and manage dispatch documents", "capability"),
        "can__InviteMembers": ("Invite Members", "Send invitations to new members", "capability"),
        "can__CreateSponsoredCircle": ("Create Sponsored Circle", "Can create a Circle sponsored by this Community", "capability"),
        "can__ManageThreadworks": ("Manage Threadworks", "Create, edit, and manage forums and discussions", "capability"),
        "can__ManageLanternmail": ("Manage Lanternmail", "Create, edit, and manage mailing lists", "capability"),
        "can__PostToStoryline": ("Post to Storyline", "Create Storyline posts in this group.", "capability"),
    }

    decorator_map = {}
    for code, (label, description, category) in phase1.items():
        decorator, _ = MembershipDecorator.objects.get_or_create(
            code=code,
            defaults={
                "label": label,
                "description": description,
                "category": category,
            },
        )
        decorator_map[code] = decorator

    user_ct = ContentType.objects.filter(app_label="users", model="customuser").first()

    for group in Group.objects.all():
        contributor, _ = GroupPermissionProfile.objects.get_or_create(
            group=group,
            code="contributor",
            defaults={
                "name": "Contributor",
                "description": "Standard member profile for Storyline participation.",
                "is_default": True,
                "sort_order": 0,
            },
        )
        moderator, _ = GroupPermissionProfile.objects.get_or_create(
            group=group,
            code="moderator",
            defaults={
                "name": "Moderator",
                "description": "Elevated member profile for moderation and management.",
                "is_default": False,
                "sort_order": 1,
            },
        )

        contributor_codes = ["can__PostToStoryline"]
        moderator_codes = list(phase1.keys())

        GroupPermissionProfileItem.objects.filter(profile=contributor).exclude(
            decorator__code__in=contributor_codes
        ).delete()
        for index, code in enumerate(contributor_codes):
            GroupPermissionProfileItem.objects.get_or_create(
                profile=contributor,
                decorator=decorator_map[code],
                defaults={"sort_order": index},
            )

        GroupPermissionProfileItem.objects.filter(profile=moderator).exclude(
            decorator__code__in=moderator_codes
        ).delete()
        for index, code in enumerate(moderator_codes):
            GroupPermissionProfileItem.objects.get_or_create(
                profile=moderator,
                decorator=decorator_map[code],
                defaults={"sort_order": index},
            )

        if not GroupPermissionProfile.objects.filter(group=group, is_default=True).exists():
            contributor.is_default = True
            contributor.save(update_fields=["is_default"])

        memberships = GroupMembership.objects.filter(group=group)
        if user_ct is not None:
            memberships = memberships.filter(member_content_type_id=user_ct.id)
        for membership in memberships.iterator():
            if membership.permission_profile_id:
                continue

            membership.permission_profile = contributor
            membership.save(update_fields=["permission_profile"])

            existing_codes = set(
                MembershipHasDecorator.objects.filter(
                    membership=membership,
                    source="profile",
                ).values_list("decorator__code", flat=True)
            )
            for code in contributor_codes:
                if code in existing_codes:
                    continue
                MembershipHasDecorator.objects.get_or_create(
                    membership=membership,
                    decorator=decorator_map[code],
                    defaults={
                        "enabled": True,
                        "source": "profile",
                        "source_profile": None,
                    },
                )


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0011_groupinvitation_delivery_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="GroupPermissionProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("code", models.SlugField(max_length=100)),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("is_default", models.BooleanField(default=False)),
                ("sort_order", models.IntegerField(default=0)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="permission_profiles", to="groups.group")),
            ],
            options={
                "db_table": "groups_grouppermissionprofile",
                "ordering": ["sort_order", "created_at"],
            },
        ),
        migrations.CreateModel(
            name="GroupPermissionProfileItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sort_order", models.IntegerField(default=0)),
                ("decorator", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="group_permission_profile_items", to="groups.membershipdecorator")),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="groups.grouppermissionprofile")),
            ],
            options={
                "db_table": "groups_grouppermissionprofileitem",
                "ordering": ["sort_order", "id"],
                "unique_together": {("profile", "decorator")},
            },
        ),
        migrations.AddField(
            model_name="grouppermissionprofile",
            name="decorators",
            field=models.ManyToManyField(blank=True, related_name="group_permission_profiles", through="groups.GroupPermissionProfileItem", to="groups.membershipdecorator"),
        ),
        migrations.AddConstraint(
            model_name="grouppermissionprofile",
            constraint=models.UniqueConstraint(fields=("group", "code"), name="groups_profile_unique_code_per_group"),
        ),
        migrations.AddConstraint(
            model_name="grouppermissionprofile",
            constraint=models.UniqueConstraint(condition=models.Q(("is_default", True)), fields=("group",), name="groups_one_default_permission_profile_per_group"),
        ),
        migrations.AddField(
            model_name="groupmembership",
            name="permission_profile",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="memberships", to="groups.grouppermissionprofile"),
        ),
        migrations.RunPython(seed_permission_profiles, migrations.RunPython.noop),
    ]
