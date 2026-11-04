from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ariadne import services
from ariadne.models import Concept, DiscoveryRun, EvidencePacket, RunCandidate

from .permissions import IsSuperuser
from .serializers import (
    ConceptDetailSerializer,
    CurationDecisionInputSerializer,
    DiscoveryRunSerializer,
    EvidencePacketDetailSerializer,
    EvidencePacketSerializer,
    PacketAssembleInputSerializer,
    RunCandidateSerializer,
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
