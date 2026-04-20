import django.dispatch

intake_submitted = django.dispatch.Signal()
# Provides: intake_session (ProspectIntakeSession instance)
