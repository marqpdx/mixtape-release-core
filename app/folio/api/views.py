# folio/api/views.py

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from folio.models import Folio, FolioInception
from .serializers import FolioInceptionCreateSerializer, FolioInceptionSerializer


class FolioInceptionListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = FolioInceptionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        raw_text = serializer.validated_data["raw_text"]
        title = serializer.validated_data.get("title", "")

        with transaction.atomic():
            folio = Folio.objects.create(title=title, created_by=request.user)
            inception = FolioInception.objects.create(
                folio=folio,
                raw_text=raw_text,
                created_by=request.user,
            )

        return Response(
            FolioInceptionSerializer(inception).data,
            status=status.HTTP_201_CREATED,
        )


class FolioInceptionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, inception_id):
        inception = get_object_or_404(
            FolioInception.objects.select_related("folio"),
            pk=inception_id,
            folio__created_by=request.user,
        )
        return Response(FolioInceptionSerializer(inception).data)
