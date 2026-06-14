from bridge.models import BridgeSession


def get_or_create_session_for_occurrence(occurrence) -> BridgeSession:
    session, _ = BridgeSession.objects.get_or_create(
        occurrence=occurrence,
        defaults={"room_name": f"bridge-{occurrence.id}"},
    )
    return session


def create_adhoc_session() -> BridgeSession:
    import uuid as _uuid
    tmp_id = _uuid.uuid4()
    session = BridgeSession.objects.create(room_name=f"bridge-adhoc-{tmp_id}")
    return session
