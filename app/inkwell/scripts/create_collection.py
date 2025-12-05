from django.conf import settings
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct


def create_qdrant_collection():

    client = QdrantClient(url=settings.QDRANT_URL)

    from qdrant_client.models import Distance, VectorParams

    client.create_collection(
        collection_name="zeke's data",
        vectors_config=VectorParams(size=4, distance=Distance.DOT),
    )

    operation_info = client.upsert(
        collection_name="test_collection",
        wait=True,
        points=[
            PointStruct(id=1, vector=[0.05, 0.61, 0.76, 0.74], payload={"city": "Kerlin"}),
            PointStruct(id=2, vector=[0.19, 0.81, 0.75, 0.11], payload={"city": "Vondon"}),
            PointStruct(id=3, vector=[0.36, 0.55, 0.47, 0.94], payload={"city": "Poscow"}),
            PointStruct(id=4, vector=[0.18, 0.01, 0.85, 0.80], payload={"city": "Wew York"}),
            PointStruct(id=5, vector=[0.24, 0.18, 0.22, 0.44], payload={"city": "Ceijing"}),
            PointStruct(id=6, vector=[0.35, 0.08, 0.11, 0.44], payload={"city": "Zumbai"}),
        ],
    )

    logger.info("Operation info: %s", operation_info)

    # operation_id=0
    # status= <UpdateStatus.COMPLETED: 'completed'>


    return ("something")
