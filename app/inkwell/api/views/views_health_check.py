from django.conf import settings
from django.http import JsonResponse
from llama_index.core import Settings
from qdrant_client import QdrantClient

from inkwell.config.ai_config import collection_name
from inkwell.scripts.startup import startup_finished
from inkwell.scripts.utils import check_rag_status, get_index


DEFAULT_COLLECTION = collection_name


# === Health Endpoints ===
def health_check(request):
    try:
        embed_model = Settings.embed_model.__class__.__name__ if Settings.embed_model else "Missing"
        index = get_index(DEFAULT_COLLECTION)
        num_nodes = len(index.docstore.docs) if index else 0
        qdrant = QdrantClient(settings.QDRANT_URL)
        collection_names = [c.name for c in qdrant.get_collections().collections]

        return JsonResponse({
            "status": "ok",
            "embed_model": embed_model,
            "retriever_ready": index is not None,
            "num_indexed_chunks": num_nodes,
            "qdrant_collections": collection_names,
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def live_check(request):
    return JsonResponse({"status": "live"})


def ready_check(request):
    if not startup_finished:
        return JsonResponse({"status": "starting", "details": check_rag_status()}, status=202)
    return JsonResponse({"status": "ready", **check_rag_status()})

