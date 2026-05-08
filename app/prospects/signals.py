import django.dispatch

intake_submitted = django.dispatch.Signal()
# Provides: intake_session (ProspectIntakeSession instance)

prospect_converted = django.dispatch.Signal()
# Provides: prospect (BusinessProspect), group (groups.Group)
