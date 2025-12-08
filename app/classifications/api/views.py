from rest_framework import generics, permissions, filters
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend

from classifications.models import ClassificationUsage, Tag, Category
from classifications.api.serializers import (
    ClassificationUsageSerializer,
    TagSerializer,
    CategorySerializer,
)


class TagListCreateView(generics.ListCreateAPIView):
    """
    List all tags or create a new tag.
    Supports filtering and search.
    """
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'summary']
    ordering_fields = ['title', 'usage_count', 'created_at']
    ordering = ['title']  # Default ordering


class TagRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a tag.
    """
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'  # Use slug instead of pk


class CategoryListCreateView(generics.ListCreateAPIView):
    """
    List all categories or create a new category.
    Supports filtering and search.
    """
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'summary']
    ordering_fields = ['title', 'usage_count', 'created_at']
    ordering = ['title']  # Default ordering


class CategoryRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a category.
    """
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'  # Use slug instead of pk


# Legacy aliases for backwards compatibility
TagList = TagListCreateView
TagDetail = TagRetrieveUpdateDestroyView









class ClassificationUsageListCreateView(generics.ListCreateAPIView):
    serializer_class = ClassificationUsageSerializer
    permission_classes = [permissions.IsAuthenticated]

    model_class = None  # You must override
    classification_model = None  # Optional (e.g. Tag or Category)

    def get_object(self):
        return get_object_or_404(self.model_class, slug=self.kwargs["slug"])

    def get_queryset(self):
        obj = self.get_object()
        ct = ContentType.objects.get_for_model(self.model_class)

        qs = ClassificationUsage.objects.filter(
            classification_client_content_type=ct,
            classification_client_object_id=obj.id,
        )

        if self.classification_model:
            allowed_ct = ContentType.objects.get_for_model(self.classification_model)
            qs = qs.filter(classification_content_type=allowed_ct)

        return qs

    def perform_create(self, serializer):
        obj = self.get_object()
        ct = ContentType.objects.get_for_model(self.model_class)
        serializer.save(
            classification_client_content_type=ct,
            classification_client_object_id=obj.id,
        )



class ClassificationUsageDeleteView(generics.DestroyAPIView):
    serializer_class = ClassificationUsageSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_url_kwarg = "usage_id"

    model_class = None  # Override

    def get_queryset(self):
        obj = get_object_or_404(self.model_class, slug=self.kwargs["slug"])
        ct = ContentType.objects.get_for_model(self.model_class)
        return ClassificationUsage.objects.filter(
            classification_client_content_type=ct,
            classification_client_object_id=obj.id,
        )
