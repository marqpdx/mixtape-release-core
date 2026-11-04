from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ariadne import inquiry as inquiry_services
from ariadne import search as search_services
from ariadne import services
from ariadne.inquiry import ModelConsentRequired
from ariadne.models import Concept, DiscoveryRun, EvidencePacket, Inquiry, InquiryReview, InquiryRun, InquiryTheme, Lens, RunCandidate

from .permissions import IsSuperuser
from .serializers import (
    ApproveSubQuestionsInputSerializer,
    ConceptDetailSerializer,
    CurateCitationInputSerializer,
    CurationDecisionInputSerializer,
    DiscoveryRunSerializer,
    DraftReviewInputSerializer,
    EvidencePacketDetailSerializer,
    EvidencePacketSerializer,
    FrameInputSerializer,
    InquiryCreateInputSerializer,
    InquiryReviewSerializer,
    InquiryRunSerializer,
    InquirySerializer,
    InquiryThemeSerializer,
    LabelThemeInputSerializer,
    PacketAssembleInputSerializer,
    RunCandidateSerializer,
    SavedSearchInputSerializer,
)


class RunDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request, run_id):
        run = get_object_or_404(DiscoveryRun, id=run_id)
        return Response(DiscoveryRunSerializer(run).data)


class LatestRunView(APIView):
    """Convenience for the workbench UI, which otherwise has no way to
    know which Run to open -- there's no Run list endpoint in this pass
    (build spec §13's illustrative GET /runs isn't built), and today
    there's exactly one real Run (2026-10-12) to point at anyway."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request):
        run = DiscoveryRun.objects.order_by("-created_at").first()
        if run is None:
            return Response({"detail": "No Discovery Run exists yet."}, status=status.HTTP_404_NOT_FOUND)
        return Response(DiscoveryRunSerializer(run).data)


class RunCandidateListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request, run_id):
        run = get_object_or_404(DiscoveryRun, id=run_id)
        candidates = run.candidates.select_related("concept").order_by("rank")
        return Response(RunCandidateSerializer(candidates, many=True).data)


class RunDecisionView(APIView):
    """§9 4B: record a disposition on one candidate. 'accept' also
    promotes the candidate's phrase to a Concept -- see services.py."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, run_id):
        run = get_object_or_404(DiscoveryRun, id=run_id)
        input_serializer = CurationDecisionInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        candidate = get_object_or_404(RunCandidate, run=run, concept_or_phrase_key=data["candidate_key"])
        services.record_decision(
            run=run, candidate=candidate, action=data["action"], reason=data["reason"], actor=request.user,
        )
        candidate.refresh_from_db()
        return Response(RunCandidateSerializer(candidate).data, status=status.HTTP_201_CREATED)


class RunPacketAssembleView(APIView):
    """§9 4C: assemble an evidence packet for one candidate, from exact
    mentions within the Run's own frozen corpus snapshot."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, run_id):
        run = get_object_or_404(DiscoveryRun, id=run_id)
        input_serializer = PacketAssembleInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        candidate_key = input_serializer.validated_data["candidate_key"]

        candidate = get_object_or_404(RunCandidate, run=run, concept_or_phrase_key=candidate_key)
        packet = services.assemble_evidence_packet(run=run, candidate=candidate)
        return Response(EvidencePacketSerializer(packet).data, status=status.HTTP_201_CREATED)

    def get(self, request, run_id):
        """List packets already assembled for this Run (most recent
        version per candidate first), so the workbench can show what's
        already been gathered without re-assembling."""
        run = get_object_or_404(DiscoveryRun, id=run_id)
        packets = run.evidence_packets.order_by("candidate_key", "-packet_version")
        return Response(EvidencePacketSerializer(packets, many=True).data)


class PacketDetailView(APIView):
    """§9 4D / §10: the packet itself, for review before any interpretation step."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request, packet_id):
        packet = get_object_or_404(EvidencePacket, id=packet_id)
        passages = services.packet_passage_detail(packet)
        serializer = EvidencePacketDetailSerializer(packet, context={"passages": passages})
        return Response(serializer.data)


class ConceptLookupView(APIView):
    """P6a (build spec §19.6, decided 2026-11-02): look up a Concept by id,
    name or alias, with its evidence. Superuser-gated, same as the rest of
    Ariadne -- this is what the three waiting consumers (Meridian's layer
    3, the Twist, the shared knowledge-mapping substrate) will eventually
    reach through Switchboard's MCP surface, once a handoff registers it
    there (not done in this pass)."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request, concept_id=None):
        if concept_id is not None:
            concept = get_object_or_404(Concept, id=concept_id)
            return Response(ConceptDetailSerializer(concept).data)

        name = request.query_params.get("name")
        alias = request.query_params.get("alias")
        if not name and not alias:
            return Response(
                {"detail": "Provide concept_id, ?name=, or ?alias="},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if name:
            concept = Concept.objects.filter(preferred_label__iexact=name).first()
        else:
            concept = Concept.objects.filter(aliases__alias__iexact=alias).first()

        if concept is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ConceptDetailSerializer(concept).data)


class SearchView(APIView):
    """P8 (build spec §19.1): hybrid search -- lexical + vector + concept
    expansion. Not an Inquiry Run (§19.2, P9); just the search primitive."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request):
        query_text = request.query_params.get("q")
        if not query_text:
            return Response({"detail": "Provide ?q=<query text>"}, status=status.HTTP_400_BAD_REQUEST)
        results = search_services.hybrid_search(query_text)
        return Response({"query": query_text, "results": results})


class SavedSearchListCreateView(APIView):
    """A saved search is a Named Lens (§19.1) -- no new object."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request):
        lenses = search_services.list_saved_searches()
        return Response(
            [
                {
                    "id": str(lens.id),
                    "name": lens.name,
                    "query": lens.active_version.config["query"],
                    "version": lens.active_version.version,
                }
                for lens in lenses
            ]
        )

    def post(self, request):
        input_serializer = SavedSearchInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        lens_version = search_services.save_search_as_lens(
            name=data["name"], query_text=data["query"], owner=request.user,
        )
        return Response(
            {
                "id": str(lens_version.lens_id),
                "name": lens_version.lens.name,
                "query": lens_version.config["query"],
                "version": lens_version.version,
            },
            status=status.HTTP_201_CREATED,
        )


class SavedSearchRunView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request, lens_id):
        lens = get_object_or_404(Lens, id=lens_id)
        results = search_services.run_saved_search(lens)
        return Response({"query": lens.active_version.config["query"], "results": results})


# ---------------------------------------------------------------------------
# P9/P9a -- Inquiry Runs and the Review artifact (build spec §19.2-19.3)
# ---------------------------------------------------------------------------

class InquiryListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request):
        inquiries = Inquiry.objects.order_by("-created_at")
        return Response(InquirySerializer(inquiries, many=True).data)

    def post(self, request):
        input_serializer = InquiryCreateInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        inquiry = inquiry_services.create_inquiry(
            question=input_serializer.validated_data["question"], actor=request.user,
        )
        return Response(InquirySerializer(inquiry).data, status=status.HTTP_201_CREATED)


class InquiryDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request, inquiry_id):
        inquiry = get_object_or_404(Inquiry, id=inquiry_id)
        return Response(InquirySerializer(inquiry).data)


class InquiryFrameView(APIView):
    """§19.2 step 1: propose or supply sub-questions. use_model=true is
    this pass's stand-in for ST-3 consent -- Frame never calls a model
    unless the caller opts in explicitly."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, inquiry_id):
        inquiry = get_object_or_404(Inquiry, id=inquiry_id)
        input_serializer = FrameInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        try:
            inquiry = inquiry_services.frame_inquiry(
                inquiry, sub_questions=data["sub_questions"], use_model=data["use_model"],
            )
        except ModelConsentRequired as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(InquirySerializer(inquiry).data)


class InquiryApproveSubQuestionsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, inquiry_id):
        inquiry = get_object_or_404(Inquiry, id=inquiry_id)
        input_serializer = ApproveSubQuestionsInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        inquiry = inquiry_services.approve_sub_questions(
            inquiry, approved_texts=input_serializer.validated_data["approved_texts"],
        )
        return Response(InquirySerializer(inquiry).data)


class InquiryGatherView(APIView):
    """§19.2 step 2: hybrid retrieval per approved sub-question."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, inquiry_id):
        inquiry = get_object_or_404(Inquiry, id=inquiry_id)
        try:
            run = inquiry_services.gather_for_inquiry(inquiry)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(InquiryRunSerializer(run).data, status=status.HTTP_201_CREATED)


class InquiryRunDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request, run_id):
        run = get_object_or_404(InquiryRun, id=run_id)
        return Response(InquiryRunSerializer(run).data)


class InquiryRunMapView(APIView):
    """§19.2 step 3: deterministic clustering over the Gather pool."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, run_id):
        run = get_object_or_404(InquiryRun, id=run_id)
        themes = inquiry_services.map_inquiry_run(run)
        return Response(InquiryThemeSerializer(themes, many=True).data, status=status.HTTP_201_CREATED)

    def get(self, request, run_id):
        run = get_object_or_404(InquiryRun, id=run_id)
        themes = run.themes.order_by("rank")
        return Response(InquiryThemeSerializer(themes, many=True).data)


class InquiryThemeLabelView(APIView):
    """Optional model step: label a theme already formed deterministically."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, theme_id):
        theme = get_object_or_404(InquiryTheme, id=theme_id)
        input_serializer = LabelThemeInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            theme = inquiry_services.label_theme(theme, use_model=input_serializer.validated_data["use_model"])
        except ModelConsentRequired as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(InquiryThemeSerializer(theme).data)


class InquiryThemePacketView(APIView):
    """§19.2 step 4: one evidence packet per theme."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, theme_id):
        theme = get_object_or_404(InquiryTheme, id=theme_id)
        packet = inquiry_services.assemble_theme_packet(theme)
        return Response(EvidencePacketSerializer(packet).data, status=status.HTTP_201_CREATED)


class InquiryRunDraftView(APIView):
    """§19.2 step 5: draft the cited Review. use_model is required --
    this is the one step that must generate prose, never deterministic."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, run_id):
        run = get_object_or_404(InquiryRun, id=run_id)
        input_serializer = DraftReviewInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        try:
            review = inquiry_services.draft_review(run, use_model=input_serializer.validated_data["use_model"])
        except ModelConsentRequired as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(InquiryReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class InquiryReviewDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def get(self, request, review_id):
        review = get_object_or_404(InquiryReview, id=review_id)
        return Response(InquiryReviewSerializer(review).data)


class InquiryReviewCurateView(APIView):
    """§19.2 step 6, minus Accession: accept, amend or strike one claim."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, review_id):
        review = get_object_or_404(InquiryReview, id=review_id)
        input_serializer = CurateCitationInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        try:
            review = inquiry_services.curate_citation(
                review, citation_id=data["citation_id"], action=data["action"], amended_text=data["amended_text"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(InquiryReviewSerializer(review).data)


class InquiryReviewAccessionView(APIView):
    """§19.2 step 6's Accession -- scoped substitute, see inquiry.py's
    module note: a plain standing-review pointer, not the real
    Likeness/accession mechanism."""

    permission_classes = [permissions.IsAuthenticated, IsSuperuser]

    def post(self, request, review_id):
        review = get_object_or_404(InquiryReview, id=review_id)
        inquiry = inquiry_services.accession_review(review)
        return Response(InquirySerializer(inquiry).data)
