from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from inkwell.client import InkwellUnavailableError
from sourcework.api.opportunity_serializers import (
    OpportunityApplicationDraftSerializer,
    OpportunityProfileSerializer,
    OpportunityStateSerializer,
    OpportunityWorkingSetSerializer,
)
from sourcework.models import OpportunityApplicationDraft, OpportunityProfile, ProvisionalData, WorkingSet
from sourcework.opportunities.application import generate_cover_letter_draft, render_cover_letter_pdf
from sourcework.opportunities.dice import DiceOpportunityAdapter
from sourcework.opportunities.dice_mcp import (
    DICE_AI_DISCLOSURE,
    DiceMCPClient,
    DiceMCPError,
    acquire_dice_search,
    plan_dice_queries,
    profile_contract,
)
from sourcework.opportunities.services import (
    ingest_opportunity_observations,
    provision_member_public_opportunity_source,
)
from sourcework.opportunities.text import extract_email_addresses, html_to_readable_text


class OpportunityProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = OpportunityProfile.objects.filter(owner_user=request.user, is_current=True).first()
        return Response({"profile": OpportunityProfileSerializer(profile).data if profile else None})

    @transaction.atomic
    def put(self, request):
        current = OpportunityProfile.objects.select_for_update().filter(
            owner_user=request.user,
            is_current=True,
        ).first()
        serializer = OpportunityProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if current:
            current.is_current = False
            current.save(update_fields=["is_current", "updated_at"])
        profile = serializer.save(
            owner_user=request.user,
            version=(current.version + 1) if current else 1,
            is_current=True,
        )
        return Response(
            {"profile": OpportunityProfileSerializer(profile).data},
            status=status.HTTP_201_CREATED if current is None else status.HTTP_200_OK,
        )


class OpportunityQueryPlanView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        membership = opportunity.working_set_memberships.select_related("working_set").first()
        source_profile_id = (
            (membership.working_set.execution_metadata or {}).get("profile_id") if membership else None
        )
        profile = None
        if source_profile_id:
            profile = OpportunityProfile.objects.filter(
                id=source_profile_id,
                owner_user=request.user,
            ).first()
        if profile is None:
            profile = get_object_or_404(OpportunityProfile, owner_user=request.user, is_current=True)
        return Response(
            {
                "profile_id": str(profile.id),
                "profile_version": profile.version,
                "queries": plan_dice_queries(profile),
                "source": "dice",
                "transport": "official_mcp",
                "disclosure": DICE_AI_DISCLOSURE,
            }
        )


class OpportunitySearchRunListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        working_sets = WorkingSet.objects.filter(
            owner_user=request.user,
            source="dice",
        ).prefetch_related("provisional_data_memberships__provisional_data")[:12]
        return Response(
            {
                "runs": OpportunityWorkingSetSerializer(working_sets, many=True).data,
                "disclosure": DICE_AI_DISCLOSURE,
            }
        )

    def post(self, request):
        profile = get_object_or_404(OpportunityProfile, owner_user=request.user, is_current=True)
        try:
            batch = acquire_dice_search(profile)
        except (DiceMCPError, OSError) as exc:
            return Response(
                {"detail": f"Dice search could not be completed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        grant = provision_member_public_opportunity_source(user=request.user)
        result = ingest_opportunity_observations(
            source_grant=grant,
            search_profile=profile_contract(profile),
            observations=batch.observations,
            adapter=DiceOpportunityAdapter(),
            user=request.user,
            title=f"Dice opportunities — {timezone.localtime():%Y-%m-%d %H:%M}",
        )
        working_set = WorkingSet.objects.get(id=result.working_set_id, owner_user=request.user)
        working_set.execution_metadata = {
            **working_set.execution_metadata,
            "transport": "official_dice_mcp",
            "query_results": list(batch.query_results),
            "profile_id": str(profile.id),
            "profile_version": profile.version,
            "resume_label": profile.resume_label,
            "resume_version": profile.resume_version,
            "disclosure": DICE_AI_DISCLOSURE,
        }
        working_set.save(update_fields=["execution_metadata", "updated_at"])
        working_set = WorkingSet.objects.prefetch_related(
            "provisional_data_memberships__provisional_data"
        ).get(id=working_set.id)
        return Response(
            {
                "run": OpportunityWorkingSetSerializer(working_set).data,
                "disclosure": DICE_AI_DISCLOSURE,
            },
            status=status.HTTP_201_CREATED,
        )


class OpportunityCandidateStateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, data_id):
        record = get_object_or_404(
            ProvisionalData,
            id=data_id,
            owner_user=request.user,
            kind="opportunity_candidate",
        )
        serializer = OpportunityStateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record.state = serializer.validated_data["state"]
        record.save(update_fields=["state", "updated_at"])
        membership = record.working_set_memberships.select_related("working_set").first()
        if not membership or membership.working_set.owner_user_id != request.user.id:
            return Response({"detail": "Opportunity updated."})
        working_set = WorkingSet.objects.prefetch_related(
            "provisional_data_memberships__provisional_data"
        ).get(id=membership.working_set_id)
        return Response({"run": OpportunityWorkingSetSerializer(working_set).data})


class OpportunityCandidateDetailsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, data_id):
        record = get_object_or_404(
            ProvisionalData,
            id=data_id,
            owner_user=request.user,
            kind="opportunity_candidate",
            source_type="dice",
        )
        try:
            details = DiceMCPClient().get_job_details(record.source_external_id)
        except (DiceMCPError, OSError) as exc:
            return Response(
                {"detail": f"Dice details could not be retrieved: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        payload = dict(record.normalized_payload or {})
        raw_description = str(details.get("description") or payload.get("description", ""))
        description = html_to_readable_text(raw_description)
        listed_emails = extract_email_addresses(description)
        raw_payload = record.raw_payload or {}
        payload["description"] = description
        payload["skills"] = [item.get("name") for item in details.get("skills", []) if item.get("name")]
        payload["easy_apply"] = bool(raw_payload.get("easyApply", payload.get("easy_apply", False)))
        payload["employer_type"] = str(raw_payload.get("employerType") or payload.get("employer_type") or "")
        payload["recruiter_name"] = str(
            details.get("recruiterName")
            or details.get("recruiter_name")
            or raw_payload.get("recruiterName")
            or payload.get("recruiter_name")
            or ""
        )
        payload["application_url"] = str(
            raw_payload.get("detailsPageUrl") or payload.get("application_url") or record.source_locator or ""
        )
        if not payload.get("contact_email") and listed_emails:
            payload["contact_email"] = listed_emails[0]
            payload["contact_email_status"] = "unverified_from_listing"
        payload["application_method"] = (
            "recruiter_email"
            if payload.get("contact_email")
            else "dice_easy_apply"
            if payload["easy_apply"]
            else "external_application"
        )
        payload["application_action"] = (
            "outbound_email_available" if payload.get("contact_email") else "manual_application_required"
        )
        payload["detail_acquired_at"] = timezone.now().isoformat()
        record.normalized_payload = payload
        record.raw_payload = {**(record.raw_payload or {}), "details": details}
        provenance = dict(record.provenance or {})
        provenance["detail_transport"] = "official_dice_mcp"
        record.provenance = provenance
        record.save(update_fields=["normalized_payload", "raw_payload", "provenance", "updated_at"])
        membership = record.working_set_memberships.select_related("working_set").first()
        working_set = WorkingSet.objects.prefetch_related(
            "provisional_data_memberships__provisional_data"
        ).get(id=membership.working_set_id)
        return Response({"run": OpportunityWorkingSetSerializer(working_set).data})


class OpportunityApplicationDraftView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, data_id):
        opportunity = self._opportunity(request, data_id)
        draft = OpportunityApplicationDraft.objects.filter(
            owner_user=request.user,
            opportunity=opportunity,
        ).select_related("profile").first()
        return Response({"draft": OpportunityApplicationDraftSerializer(draft).data if draft else None})

    def post(self, request, data_id):
        opportunity = self._opportunity(request, data_id)
        if not (opportunity.normalized_payload or {}).get("detail_acquired_at"):
            return Response(
                {"detail": "Retrieve the full listing before drafting application material."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        profile = get_object_or_404(OpportunityProfile, owner_user=request.user, is_current=True)
        try:
            draft = generate_cover_letter_draft(
                opportunity=opportunity,
                profile=profile,
                owner=request.user,
            )
        except (InkwellUnavailableError, ValueError) as exc:
            return Response(
                {"detail": f"Cover-letter draft could not be generated: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {"draft": OpportunityApplicationDraftSerializer(draft).data},
            status=status.HTTP_201_CREATED,
        )

    def put(self, request, data_id):
        opportunity = self._opportunity(request, data_id)
        draft = get_object_or_404(
            OpportunityApplicationDraft,
            owner_user=request.user,
            opportunity=opportunity,
        )
        serializer = OpportunityApplicationDraftSerializer(draft, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"draft": serializer.data})

    @staticmethod
    def _opportunity(request, data_id):
        return get_object_or_404(
            ProvisionalData,
            id=data_id,
            owner_user=request.user,
            kind="opportunity_candidate",
        )


class OpportunityApplicationDraftPDFView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, data_id):
        opportunity = get_object_or_404(
            ProvisionalData,
            id=data_id,
            owner_user=request.user,
            kind="opportunity_candidate",
        )
        draft = get_object_or_404(
            OpportunityApplicationDraft,
            owner_user=request.user,
            opportunity=opportunity,
        )
        if not draft.letter_body.strip():
            return Response({"detail": "The cover letter is empty."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            pdf_bytes = render_cover_letter_pdf(draft=draft)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if len(pdf_bytes) > 2 * 1024 * 1024:
            return Response(
                {"detail": "The generated PDF exceeds Dice's 2 MB upload limit."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        payload = opportunity.normalized_payload or {}
        filename = slugify(f"cover-letter-{payload.get('organization') or payload.get('title') or 'opportunity'}")
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
        return response
