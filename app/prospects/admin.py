from django.contrib import admin
from django.db import transaction

from .models import (
    BusinessProspect,
    OnboardingQuestion,
    ProspectInsight,
    ProspectIntakeSession,
    ProspectNote,
    ProspectQuestion,
    ProspectQuestionOnboardingMap,
    ProspectResponse,
)


@admin.register(BusinessProspect)
class BusinessProspectAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "primary_contact_email", "converted_to_group", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "primary_contact_email")
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("sponsor_content_type",)
    readonly_fields = ("org_description", "knowledge_goal")
    actions = ["activate_as_catalyst_client", "link_existing_group_as_catalyst_tenant"]

    @admin.action(description="Activate as Catalyst client (provisions Group + Client record)")
    def activate_as_catalyst_client(self, request, queryset):
        from business.models import Client
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from django.utils.text import slugify
        from groups.models.group import Group
        from groups.models.dec_enums import GroupType, GroupVisibility
        from groups.services.memberships import ensure_user_membership

        User = get_user_model()

        if queryset.count() != 1:
            self.message_user(request, "Select exactly one prospect to activate.", level="error")
            return

        prospect = queryset.first()

        if prospect.converted_to_group_id:
            self.message_user(
                request,
                f"'{prospect.name}' is already linked to group '{prospect.converted_to_group}'. "
                "No changes made.",
                level="error",
            )
            return

        if not prospect.slug:
            self.message_user(
                request,
                f"'{prospect.name}' has no slug set. Add one before activating.",
                level="error",
            )
            return

        if Group.objects.filter(slug=prospect.slug).exists():
            self.message_user(
                request,
                f"A Group with slug '{prospect.slug}' already exists. "
                "Resolve the conflict before activating.",
                level="error",
            )
            return

        with transaction.atomic():
            # Mirror the self-sponsor bootstrap from provision_tenant
            group = Group(
                slug=prospect.slug,
                title=prospect.name,
                group_type=GroupType.COMMUNITY,
                visibility=GroupVisibility.PUBLIC,
                is_active=True,
                catalyst_enabled=True,
                in_crossroads_commons=False,
            )
            ct = ContentType.objects.get_for_model(Group)
            group.sponsor_content_type = ct
            group.sponsor_object_id = group.id
            group.save()

            Client.objects.create(
                group=group,
                prospect=prospect,
                primary_contact_name=prospect.primary_contact_name,
                primary_contact_email=prospect.primary_contact_email,
                primary_contact_phone=prospect.primary_contact_phone,
                website=prospect.website,
                business_type=prospect.business_type,
                created_by=request.user,
            )

            # Create or get a user account for the primary contact, add as owner
            contact_email = prospect.primary_contact_email
            owner_user = None
            if contact_email:
                owner_user, user_created = User.objects.get_or_create(
                    email=contact_email,
                    defaults={
                        "username": slugify(contact_email.split("@")[0])[:150],
                        "is_active": False,  # inactive until they set a password via invite
                    },
                )
                ensure_user_membership(group, owner_user, role="owner")

            prospect.converted_to_group = group
            prospect.status = "won"
            prospect.save(update_fields=["converted_to_group", "status", "updated_at"])

        user_note = (
            f" User '{contact_email}' created (inactive) and set as owner."
            if contact_email and user_created
            else f" User '{contact_email}' already existed — set as owner."
            if contact_email and not user_created
            else " No primary_contact_email set — no user created."
        )
        self.message_user(
            request,
            f"Activated '{prospect.name}' — Group '{group.slug}' (pk={group.pk}) and Client "
            f"record created.{user_note} Next: run activate_catalyst_tenant --slug={group.slug}",
            level="success",
        )

    @admin.action(description="Link existing Group as Catalyst tenant (no new Group created)")
    def link_existing_group_as_catalyst_tenant(self, request, queryset):
        """
        For orgs that already have a Group in Mixtape. Sets catalyst_enabled=True on
        the existing Group, creates a Client record, and adds the primary contact as
        owner — without creating a new Group.

        Precondition: prospect.slug must match the slug of the existing Group exactly.
        If it doesn't, edit the prospect slug in admin to match before running this action.
        """
        from business.models import Client
        from django.contrib.auth import get_user_model
        from django.utils.text import slugify
        from groups.models.group import Group
        from groups.services.memberships import ensure_user_membership

        User = get_user_model()

        if queryset.count() != 1:
            self.message_user(request, "Select exactly one prospect to activate.", level="error")
            return

        prospect = queryset.first()

        if prospect.converted_to_group_id:
            self.message_user(
                request,
                f"'{prospect.name}' is already linked to group '{prospect.converted_to_group}'. "
                "No changes made.",
                level="error",
            )
            return

        if not prospect.slug:
            self.message_user(
                request,
                f"'{prospect.name}' has no slug. Set it to match the existing Group's slug before activating.",
                level="error",
            )
            return

        try:
            group = Group.objects.get(slug=prospect.slug)
        except Group.DoesNotExist:
            self.message_user(
                request,
                f"No Group found with slug '{prospect.slug}'. "
                "Use 'Activate as Catalyst client' to create a new one, or update the prospect slug.",
                level="error",
            )
            return

        if hasattr(group, "client"):
            self.message_user(
                request,
                f"Group '{group.slug}' already has a Client record. No changes made.",
                level="error",
            )
            return

        with transaction.atomic():
            group.catalyst_enabled = True
            group.save(update_fields=["catalyst_enabled", "updated_at"])

            contact_email = prospect.primary_contact_email
            owner_user = None
            user_created = False
            if contact_email:
                owner_user, user_created = User.objects.get_or_create(
                    email=contact_email,
                    defaults={
                        "username": slugify(contact_email.split("@")[0])[:150],
                        "is_active": False,
                    },
                )
                ensure_user_membership(group, owner_user, role="owner")

            Client.objects.create(
                group=group,
                prospect=prospect,
                primary_contact_name=prospect.primary_contact_name,
                primary_contact_email=contact_email,
                primary_contact_phone=prospect.primary_contact_phone,
                website=prospect.website,
                business_type=prospect.business_type,
                created_by=request.user,
            )

            prospect.converted_to_group = group
            prospect.status = "won"
            prospect.save(update_fields=["converted_to_group", "status", "updated_at"])

        user_note = (
            f" User '{contact_email}' created (inactive) and set as owner."
            if contact_email and user_created
            else f" User '{contact_email}' already existed — confirmed as owner."
            if contact_email and not user_created
            else " No primary_contact_email — no user created."
        )
        self.message_user(
            request,
            f"Linked existing Group '{group.slug}' (pk={group.pk}) as Catalyst tenant. "
            f"catalyst_enabled set, Client record created.{user_note} "
            f"Next: run activate_catalyst_tenant --slug={group.slug}",
            level="success",
        )

    def has_module_perms(self, request, app_label=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(ProspectIntakeSession)
class ProspectIntakeSessionAdmin(admin.ModelAdmin):
    list_display = ("prospect", "mode", "status", "submitted_at")
    list_filter = ("status", "mode")
    raw_id_fields = ("prospect",)
    readonly_fields = ("resume_token",)


@admin.register(ProspectQuestion)
class ProspectQuestionAdmin(admin.ModelAdmin):
    list_display = ("order_index", "prompt", "is_active", "question_kind")
    list_display_links = ("prompt",)
    list_editable = ("order_index", "is_active")


@admin.register(ProspectResponse)
class ProspectResponseAdmin(admin.ModelAdmin):
    list_display = ("intake_session", "question", "kind", "processing_status", "created_at")
    raw_id_fields = ("intake_session", "question")


@admin.register(ProspectInsight)
class ProspectInsightAdmin(admin.ModelAdmin):
    list_display = ("prospect", "kind", "source", "title", "created_at")
    list_filter = ("kind", "source")


@admin.register(ProspectNote)
class ProspectNoteAdmin(admin.ModelAdmin):
    list_display = ("prospect", "created_by", "created_at")
    raw_id_fields = ("prospect",)


@admin.register(OnboardingQuestion)
class OnboardingQuestionAdmin(admin.ModelAdmin):
    list_display = ("category", "order", "text_preview", "triggers_persona_creation", "is_active")
    list_filter = ("category", "is_active", "triggers_persona_creation")
    list_editable = ("order", "is_active")

    def text_preview(self, obj):
        return obj.text[:80]
    text_preview.short_description = "text"


@admin.register(ProspectQuestionOnboardingMap)
class ProspectQuestionOnboardingMapAdmin(admin.ModelAdmin):
    list_display = ("prospect_question", "onboarding_question")
    raw_id_fields = ("prospect_question", "onboarding_question")
