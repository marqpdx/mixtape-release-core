# surfaces/migrations/0002_seed_surface_profiles.py
#
# Seeds the six Surface profiles named in ADR-0064 D8. Write grants here
# follow R3's ladder as it stands at ratification (charter-amendment-
# surface-profiles.md §2, table): Argus holds "own records" (its run
# records, to argus-runs); Puddlejump holds "canon writer"; every other
# profile holds "none" (the default) until a build gives it a grant.
# Persona text is left blank here — Argus's persona comes from
# operations/scripts/argus-run.sh's existing prompt assembly (AC-2/AC-4),
# not duplicated into this seed.

from django.db import migrations


PROFILES = [
    dict(
        slug="atrium",
        name="Atrium",
        kind="member",
        agent_host="crossroads",
        who_may_enter="members",
        write_grant="none",
        consent_rule="press_each_time",
    ),
    dict(
        slug="catalyst",
        name="Catalyst",
        kind="member",
        agent_host="crossroads",
        who_may_enter="members",
        write_grant="none",
        consent_rule="press_each_time",
    ),
    dict(
        slug="writing",
        name="Writing",
        kind="member",
        agent_host="crossroads",
        who_may_enter="members",
        write_grant="none",
        consent_rule="press_each_time",
    ),
    dict(
        slug="argus",
        name="Argus",
        kind="builder",
        agent_host="cass",
        who_may_enter="builders",
        write_grant="own_records",
        consent_rule="run_series",
    ),
    dict(
        slug="puddlejump",
        name="Puddlejump",
        kind="builder",
        agent_host="cass",
        who_may_enter="builders",
        write_grant="canon_writer",
        consent_rule="press_each_time",
    ),
    dict(
        slug="sysadmin",
        name="SysAdmin",
        kind="builder",
        agent_host="cass",
        who_may_enter="builders",
        write_grant="none",
        consent_rule="press_each_time",
    ),
]


def seed_profiles(apps, schema_editor):
    SurfaceProfile = apps.get_model("surfaces", "SurfaceProfile")
    for profile in PROFILES:
        SurfaceProfile.objects.update_or_create(slug=profile["slug"], defaults=profile)


def unseed_profiles(apps, schema_editor):
    SurfaceProfile = apps.get_model("surfaces", "SurfaceProfile")
    SurfaceProfile.objects.filter(slug__in=[p["slug"] for p in PROFILES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("surfaces", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_profiles, unseed_profiles),
    ]
