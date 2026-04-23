from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from console import services


class ReentryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"items": services.get_reentry_items(request.user)})


class SignalsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.get_signals(request.user))


class OrientationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.get_orientation(request.user))


class StewardshipView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(services.get_stewardship(request.user))
