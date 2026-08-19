from django.urls import path

from .views import (
    OcrSpikeArtifactDetailView,
    OcrSpikeArtifactListCreateView,
    OcrSpikeArtifactPagesView,
    OcrSpikeArtifactRunLocalView,
    OcrSpikeFeedbackView,
    OcrSpikePageCloudRecognizeView,
    OcrSpikePageEvaluationView,
    OcrSpikePageFileView,
)

urlpatterns = [
    path("artifacts/", OcrSpikeArtifactListCreateView.as_view(), name="ocr-spike-artifacts"),
    path("artifacts/<uuid:artifact_id>/", OcrSpikeArtifactDetailView.as_view(), name="ocr-spike-artifact-detail"),
    path("artifacts/<uuid:artifact_id>/run-local/", OcrSpikeArtifactRunLocalView.as_view(), name="ocr-spike-run-local"),
    path("artifacts/<uuid:artifact_id>/pages/", OcrSpikeArtifactPagesView.as_view(), name="ocr-spike-artifact-pages"),
    path("pages/<uuid:page_id>/file/", OcrSpikePageFileView.as_view(), name="ocr-spike-page-file"),
    path("pages/<uuid:page_id>/cloud-recognize/", OcrSpikePageCloudRecognizeView.as_view(), name="ocr-spike-cloud-recognize"),
    path("pages/<uuid:page_id>/evaluation/", OcrSpikePageEvaluationView.as_view(), name="ocr-spike-page-evaluation"),
    path("feedback/", OcrSpikeFeedbackView.as_view(), name="ocr-spike-feedback"),
]
