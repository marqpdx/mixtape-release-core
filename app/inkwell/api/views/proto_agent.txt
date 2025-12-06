# ai/views/proto_agent.py

import logging
logger = logging.getLogger(__name__)

from collections import defaultdict
from django.db import models
from django.db.models import Q
from rest_framework import status
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from inkwell.api.serializers import BlacklistedTitleSerializer, SuggestedAssetSerializer, SuggestedAssetUpdateSerializer
from inkwell.models import BlacklistedTitle, DeletedAsset, DeletedGutenbergInfo, IngestedAsset, SuggestedAsset
from inkwell.models import DeclinedAsset, ProtoAgentTask, IngestedFile
from inkwell.utils.agent_launcher import launch_agents_for_task
from inkwell.utils.asset_actions import preapprove_asset
from inkwell.utils.asset_creation import create_suggested_asset
from inkwell.utils.gutenberg_scraper import create_suggested_asset_from_url, get_gutenberg_suggestions
from inkwell.utils.ingest_thread import start_retrieval_agent

class SuggestAssetsView(APIView):

    def get_queryset(self):
        status = self.request.query_params.get("status")
        queryset = SuggestedAsset.objects.all()

        if status == "suggested":
            # Exclude declined and deleted, and not yet approved/retrieved
            queryset = queryset.filter(
                Q(declined_asset__isnull=True) &
                Q(deleted_asset__isnull=True) &
                Q(approved=False) &
                Q(retrieved=False)
            )
        elif status == "declined":
            queryset = queryset.filter(declined_asset__isnull=False)
        elif status == "approved":
            queryset = queryset.filter(approved=True)
        elif status == "deleted":
            queryset = queryset.filter(deleted_asset__isnull=False)
        # else, return everything (or restrict as needed)

        return queryset

    def get(self, request):
        queryset = self.get_queryset().order_by("-suggested_at")
        serialized = SuggestedAssetSerializer(queryset, many=True)
        return Response(serialized.data)

    def post(self, request):
        keywords = request.data.get("keywords", [])
        count = int(request.data.get("count", 10))

        declined_ids = set(
            DeclinedAsset.objects.values_list("suggested_asset_id", flat=True)
        )
        ingested_ids = set(IngestedFile.objects.values_list("filehash", flat=True))
        suggested_ids = set(
            SuggestedAsset.objects.filter(source="gutenberg").values_list("source_id", flat=True)
        )

        new_suggestions = get_gutenberg_suggestions(
            keywords,
            count,
            exclude_ids=ingested_ids.union(declined_ids).union(suggested_ids),
        )

        for asset_data in new_suggestions:
            create_suggested_asset(asset_data)

        candidates = self.get_queryset().order_by("-suggested_at")[:count]

        data = [{
            "id": b.id,
            "title": b.title,
            "author": b.author,
            "tags": b.subject_tags,
            "status": b.status,
            # "text_url": b.text_url,
            "cover_url": b.cover_url,
            "score": b.score,
            "synopsis_status": b.synopsis_status,
            "source": b.source,
        } for b in candidates]

        return Response(data)


class DeclineAssetView(APIView):
    def post(self, request):
        asset_id = request.data.get("asset_id")
        reason = request.data.get("reason", "")

        try:
            asset = SuggestedAsset.objects.get(id=asset_id)
        except SuggestedAsset.DoesNotExist:
            return Response({"error": "Suggested asset not found"}, status=404)

        # Prevent duplicate declines
        if hasattr(asset, "declined_asset"):
            return Response({"status": "already_declined"})

        DeclinedAsset.objects.create(
            suggested_asset=asset,
            reason=reason
        )

        return Response({"status": "declined"})


class DeleteAssetView(APIView):
    def post(self, request):
        asset_id = request.data.get("asset_id")

        if not asset_id:
            return Response({"error": "Missing asset_id"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            asset = SuggestedAsset.objects.get(id=asset_id)
            logger.debug('Asset: %s', asset)
        except SuggestedAsset.DoesNotExist:
            return Response({"error": "Suggested asset not found"}, status=status.HTTP_404_NOT_FOUND)

        # Record the deletion
        deleted_asset = DeletedAsset.objects.create(
            suggested_asset=asset,
            deleted_title=asset.title,
            deleted_author=asset.author,
        )

        if asset.source == "gutenberg":
            if hasattr(asset, "gutenberg_info") and asset.gutenberg_info:
                DeletedGutenbergInfo.objects.create(
                    deleted_asset=deleted_asset,
                    gutenberg_id=asset.gutenberg_info.gutenberg_id,
                )
            else:
                logger.warning(" No gutenberg_info found for asset %s — skipping gutenberg_id recording.", asset.id)


        # Delete the SuggestedAsset itself
        asset.delete()

        return Response({"status": "deleted"}, status=status.HTTP_200_OK)


class PreApproveAssetView(APIView):
    def post(self, request):
        asset_ids = request.data.get("asset_ids", [])
        if not asset_ids:
            return Response({"error": "No asset_ids provided"}, status=400)

        updated = 0
        for asset in SuggestedAsset.objects.filter(id__in=asset_ids, approved=False):
            preapprove_asset(asset, trigger_synopsis=True)
            updated += 1

        return Response({
            "status": "approved",
            "approved_count": updated
        })


class ApproveAssetView(APIView):
    def post(self, request):
        asset_ids = request.data.get("asset_ids", [])
        if not asset_ids:
            return Response({"error": "No asset_ids provided"}, status=400)

        updated = SuggestedAsset.objects.filter(id__in=asset_ids, approved=False).update(approved=True)

        from inkwell.tasks.ingest import ingest_approved_asset_task
        logger.debug(" Task object (view): %r", ingest_approved_asset_task)

        for asset_id in asset_ids:
            try:
                asset = SuggestedAsset.objects.get(id=asset_id)
                asset.ingestion_status = "queued"
                asset.save()

                logger.info("🚀 Ingest triggered for asset {asset_id}")
                # logger.info("📨 Calling .delay() for asset {asset_id}")
                ingest_approved_asset_task.delay(asset_id)

            except SuggestedAsset.DoesNotExist:
                logger.error(" Asset with ID %s not found in ApproveAssetView", asset_id)

        return Response({
            "status": "approved",
            "approved_count": updated
        })


class RetrieveAssetsView(APIView):
    def post(self, request):
        ids = request.data.get("asset_ids", [])
        if not ids:
            return Response({"error": "No asset_ids provided"}, status=400)

        assets = SuggestedAsset.objects.filter(id__in=ids, approved=True, retrieved=False)



        for asset in assets:
            start_retrieval_agent(asset)

        return Response({"status": "retrieval started", "count": assets.count()})


class LaunchAgentsView(APIView):
    def post(self, request):
        keyword_sets = request.data.get("keyword_sets", [])  # list of lists
        assets_per_agent = int(request.data.get("assets_per_agent", 5))

        if not keyword_sets or not isinstance(keyword_sets, list):
            return Response({"error": "Invalid keyword_sets"}, status=400)

        task = ProtoAgentTask.objects.create(
            keyword_list=keyword_sets,
            assets_per_agent=assets_per_agent,
        )

        launch_agents_for_task(task)

        return Response({"status": "agents launched", "task_id": task.id})


class ListApprovedAssetsView(APIView):
    def get(self, request):
        assets = SuggestedAsset.objects.all()
        assets = assets.exclude(id__in=DeclinedAsset.objects.values("suggested_asset_id"))
        assets = assets.exclude(id__in=DeletedAsset.objects.values("suggested_asset_id"))

        grouped = defaultdict(list)
        for asset in assets:
            grouped[asset.asset_type].append({
                "id": asset.id,
                "title": asset.title,
                "author": asset.author,
                "tags": asset.subject_tags,
                "status": asset.status,
                "text_url": asset.gutenberg_info.text_url if hasattr(asset, 'gutenberg_info') else None,
                "retrieved": asset.retrieved,
                "synopsis": asset.synopsis,
                "source": asset.source,
                "suggested_at": asset.suggested_at,
            })

        return Response(grouped)


class RetrieveAllAssetsView(APIView):
    def post(self, request):
        assets = SuggestedAsset.objects.filter(approved=True, retrieved=False)

        if not assets.exists():
            return Response({"status": "no approved assets to retrieve"}, status=200)

        for asset in assets:
            start_retrieval_agent(asset)

        return Response({
            "status": "retrieval started",
            "count": assets.count()
        })


class SynopsisStatusView(APIView):
    def get(self, request):
        from inkwell.models import SuggestedAsset
        status_counts = (
            SuggestedAsset.objects
            .values("synopsis_status")
            .order_by()
            .annotate(count=models.Count("id"))
        )

        return Response({s["synopsis_status"] or "unknown": s["count"] for s in status_counts})


class BlacklistedTitleViewSet(viewsets.ModelViewSet):
    queryset = BlacklistedTitle.objects.all()
    serializer_class = BlacklistedTitleSerializer


class UpdateSuggestedAssetView(APIView):
    def patch(self, request, pk):
        try:
            asset = SuggestedAsset.objects.get(pk=pk)
        except SuggestedAsset.DoesNotExist:
            return Response({"error": "Asset not found"}, status=404)

        serializer = SuggestedAssetUpdateSerializer(asset, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)


class SuggestAssetFromUrlView(APIView):
    def post(self, request):
        url = request.data.get("url")
        if not url:
            return Response({"error": "Missing URL"}, status=400)

        try:
            asset = create_suggested_asset_from_url(url)
            return Response(SuggestedAssetSerializer(asset).data)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)



class IngestedCatalogView(APIView):
    def get(self, request):
        assets = IngestedAsset.objects.select_related("suggested_asset", "ingestedfile").order_by("-ingested_at")[:100]
        data = [{
            "id": asset.id,
            "title": asset.suggested_asset.title,
            "author": asset.suggested_asset.author,
            "ingested_at": asset.ingested_at,
            "source": asset.suggested_asset.source,
            "source_url": asset.ingestedfile.source_url if hasattr(asset, "ingestedfile") else None,
        } for asset in assets]
        return Response(data)

