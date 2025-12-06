# ai/api/views/blacklist.py

from rest_framework import viewsets

from inkwell.api.serializers import BlacklistedTitleSerializer
from inkwell.models import BlacklistedTitle


class BlacklistedTitleViewSet(viewsets.ModelViewSet):
    queryset = BlacklistedTitle.objects.all()
    serializer_class = BlacklistedTitleSerializer
