from django.db import migrations


def add_ispersonabrand(apps, schema_editor):
    GroupDecorator = apps.get_model('groups', 'GroupDecorator')
    GroupDecorator.objects.get_or_create(
        code='isPersonaBrand',
        defaults={
            'category': 'identity',
            'label': 'Persona Brand',
            'description': (
                'Marks a Community as the personal brand presence of its founding member. '
                'Only valid on Community groups.'
            ),
            'valid_for_types': ['community'],
            'sort_order': 10,
        }
    )


def remove_ispersonabrand(apps, schema_editor):
    GroupDecorator = apps.get_model('groups', 'GroupDecorator')
    GroupDecorator.objects.filter(code='isPersonaBrand').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('groups', '0020_remove_personagroup'),
    ]

    operations = [
        migrations.RunPython(add_ispersonabrand, remove_ispersonabrand),
    ]
