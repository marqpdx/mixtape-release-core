from django.db import migrations


def add_circle_catalog(apps, schema_editor):
    GroupDecorator = apps.get_model('groups', 'GroupDecorator')
    GroupDecoratorProfile = apps.get_model('groups', 'GroupDecoratorProfile')
    GroupProfileItem = apps.get_model('groups', 'GroupProfileItem')

    decorator, _ = GroupDecorator.objects.get_or_create(
        code='hasDeliverableIntent',
        defaults={
            'category': 'capability',
            'label': 'Deliverable Intent',
            'description': (
                'Activates deliverable tracking on a Circle: declares the type of outcome '
                '(puddlejump_doc, dispatch, or finding), its lifecycle status, and optionally '
                'links to the produced artifact via an ArtifactRelation. Only valid on Circles.'
            ),
            'valid_for_types': ['circle'],
            'sort_order': 10,
        }
    )

    profile, _ = GroupDecoratorProfile.objects.get_or_create(
        code='profile__WorkingCircle',
        defaults={
            'label': 'Working Circle',
            'description': (
                'Bundle profile for task-focused, outcome-oriented Circles. Applies '
                'hasDeliverableIntent and any appropriate capability decorators as '
                'independent rows (bundle-as-template). Removal is not cascading.'
            ),
            'valid_for_types': ['circle'],
            'is_active': True,
            'sort_order': 10,
        }
    )

    GroupProfileItem.objects.get_or_create(
        profile=profile,
        decorator=decorator,
        defaults={'sort_order': 10, 'is_required': True},
    )


def remove_circle_catalog(apps, schema_editor):
    GroupDecoratorProfile = apps.get_model('groups', 'GroupDecoratorProfile')
    GroupDecorator = apps.get_model('groups', 'GroupDecorator')

    GroupDecoratorProfile.objects.filter(code='profile__WorkingCircle').delete()
    GroupDecorator.objects.filter(code='hasDeliverableIntent').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('groups', '0022_add_circle_parent_and_visibility'),
    ]

    operations = [
        migrations.RunPython(add_circle_catalog, remove_circle_catalog),
    ]
