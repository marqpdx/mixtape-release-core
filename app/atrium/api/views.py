# atrium/api/views.py
#
# Atrium Dialogues (ST-3 Part B, 2026-11-04). A person's message is saved here and
# the reply is written on the runtime worker, as the Dialogue owner's own account
# (atrium/turns.py); the exchange and follow views relay it to the page as it is
# written (atrium/relay.py). Nothing here runs a model.

import json
import logging
import time

from django.db.models import F, Count
from django.http import StreamingHttpResponse

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from atrium.models import (
    AtriumDialMode,
    CloudAgentSession,
    Dialogue,
    DialogueEntry,
    DialogueEntryStatus,
    DialogueStatus,
    Distillate,
    DistillateDocumentType,
    DistillateStatus,
)
from profiles.services.profiles import ensure_user_profile

from .serializers import DialogueEntrySerializer, DialogueListSerializer, DistillateSerializer

logger = logging.getLogger(__name__)

# What the page is told when a reply stops, by code. The person's message is kept.
REPLY_STOP_MESSAGES = {
    "runtime_missing": "Connect your AI account in Settings → AI accounts to use this agent.",
    "runtime_not_ready": "Your AI account needs signing in again: Settings → AI accounts.",
    "mode_not_allowed": "Atrium isn't turned on for your AI account.",
    "provider_not_supported": "That agent isn't available in Atrium.",
    "failed": "The agent stopped before finishing. Your message is saved; try again.",
}

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
_FOLLOW_LIMIT_SECONDS = 600
_KEEPALIVE_SECONDS = 15
_WAIT_SECONDS = 1.0


def _sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


def _own_dialogue(request, dialogue_id):
    profile = ensure_user_profile(request.user)
    return (
        Dialogue.objects.select_related("sponsor_content_type", "member")
        .filter(id=dialogue_id, member=profile, deleted_at__isnull=True)
        .first()
    )


def _not_found():
    return Response({"detail": "Dialogue not found."}, status=status.HTTP_404_NOT_FOUND)


def follow_reply(entry_id, *, opening: dict | None = None):
    """
    Yield a reply as SSE while the runtime worker writes it.

    Events: turn (once, with the entry id and speaker), delta (new text), then either
    final (the finished entry: its content may differ from the streamed text when a
    document envelope was unwrapped) followed by done, or error (with its code).
    """
    from atrium import relay

    if opening:
        yield _sse(opening)
    sent = 0
    started = time.monotonic()
    last_beat = started
    with relay.listener(entry_id) as wait:
        while True:
            row = (
                DialogueEntry.objects.filter(pk=entry_id)
                .values("content", "status", "error_code", "entry_type", "document_title", "speaker")
                .first()
            )
            if row is None:
                yield _sse({"type": "error", "code": "failed", "detail": "The reply was removed."})
                return
            content = row["content"] or ""
            if row["status"] in (DialogueEntryStatus.STREAMING, DialogueEntryStatus.PENDING) and len(content) > sent:
                yield _sse({"type": "delta", "text": content[sent:]})
                sent = len(content)
            if row["status"] == DialogueEntryStatus.DONE:
                yield _sse({
                    "type": "final",
                    "entry_id": str(entry_id),
                    "speaker": row["speaker"],
                    "content": content,
                    "entry_type": row["entry_type"],
                    "document_title": row["document_title"],
                })
                yield _sse({"type": "done"})
                return
            if row["status"] == DialogueEntryStatus.FAILED:
                code = row["error_code"] or "failed"
                yield _sse({
                    "type": "error",
                    "code": code,
                    "detail": REPLY_STOP_MESSAGES.get(code, REPLY_STOP_MESSAGES["failed"]),
                    "partial": content,
                })
                return
            now = time.monotonic()
            if now - started > _FOLLOW_LIMIT_SECONDS:
                yield _sse({"type": "error", "code": "still_running", "detail": "Still working; reopen the Dialogue to see the reply."})
                return
            if now - last_beat > _KEEPALIVE_SECONDS:
                yield b": keepalive\n\n"
                last_beat = now
            wait(_WAIT_SECONDS)


def _exchange_response(request, dialogue):
    from atrium.turns import DIALOGUE_PROVIDERS, start_turn

    if dialogue.status == DialogueStatus.ARCHIVED:
        return Response({"detail": "Dialogue is archived."}, status=status.HTTP_400_BAD_REQUEST)

    message = (request.data.get("message") or "").strip()
    if not message:
        return Response({"detail": "message is required."}, status=status.HTTP_400_BAD_REQUEST)

    provider = request.data.get("provider") or None
    if provider is not None and provider not in DIALOGUE_PROVIDERS:
        return Response(
            {"detail": f"provider must be one of: {', '.join(DIALOGUE_PROVIDERS)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    reply = start_turn(dialogue, request.user, message, provider)
    logger.info("atrium_exchange dialogue=%s entry=%s speaker=%s", dialogue.id, reply.id, reply.speaker)
    opening = {"type": "turn", "entry_id": str(reply.id), "speaker": reply.speaker}
    return StreamingHttpResponse(
        follow_reply(reply.id, opening=opening),
        content_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


class DialogueListView(generics.ListAPIView):
    """
    GET /api/atrium/dialogues/

    The member's Dialogues, active first then by most recent activity, capped at 50,
    with entry_count. ?group_slug= for a Group's; ?personal=true for personal ones.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = DialogueListSerializer

    def get_queryset(self):
        profile = ensure_user_profile(self.request.user)
        qs = Dialogue.objects.filter(member=profile, deleted_at__isnull=True)

        group_slug = self.request.query_params.get("group_slug", "")
        if group_slug:
            from django.contrib.contenttypes.models import ContentType
            from groups.models.group import Group
            group = Group.objects.filter(slug=group_slug, deleted_at__isnull=True).first()
            if group:
                ct = ContentType.objects.get_for_model(Group)
                qs = qs.filter(sponsor_content_type=ct, sponsor_object_id=group.pk)
            else:
                qs = qs.none()
        elif self.request.query_params.get("personal") == "true":
            qs = qs.filter(sponsor_object_id__isnull=True)

        initiative_id = self.request.query_params.get("initiative_id", "")
        if initiative_id:
            qs = qs.filter(initiative_id=initiative_id)

        return (
            qs.annotate(entry_count=Count("entries"))
            .order_by("status", "-last_activity_at", "-created_at")[:50]
        )


class DialogueCreateView(generics.CreateAPIView):
    """
    POST /api/atrium/dialogues/new

    Body: { title?, session_context?, group_slug?, initiative_id?, ai_provider? }
    """

    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        from atrium.turns import DIALOGUE_PROVIDERS

        profile = ensure_user_profile(request.user)

        sponsor_ct = None
        sponsor_id = None
        group_slug = request.data.get("group_slug", "")
        if group_slug:
            from django.contrib.contenttypes.models import ContentType
            from groups.models.group import Group
            group = Group.objects.filter(slug=group_slug, deleted_at__isnull=True).first()
            if group:
                sponsor_ct = ContentType.objects.get_for_model(Group)
                sponsor_id = group.pk

        initiative = None
        initiative_id = request.data.get("initiative_id", "")
        if initiative_id:
            from initiatives.models import Initiative
            initiative = Initiative.objects.filter(id=initiative_id, deleted_at__isnull=True).first()
        if initiative is None and sponsor_id is None:
            # A personal Dialogue lives in the member's Initiative Zero.
            from atrium.initiative_zero import initiative_zero

            initiative = initiative_zero(request.user)

        ai_provider = request.data.get("ai_provider") or Dialogue._meta.get_field("ai_provider").default
        if ai_provider not in DIALOGUE_PROVIDERS:
            return Response(
                {"detail": f"ai_provider must be one of: {', '.join(DIALOGUE_PROVIDERS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dialogue = Dialogue.objects.create(
            member=profile,
            title=request.data.get("title", ""),
            session_context=request.data.get("session_context", ""),
            ai_provider=ai_provider,
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=sponsor_id,
            initiative=initiative,
        )
        return Response(DialogueListSerializer(dialogue).data, status=status.HTTP_201_CREATED)


def _can_open_initiative(user, initiative) -> bool:
    """The person may hold Dialogues in an Initiative they sponsor, or one of their Group's."""
    if user.is_staff:
        return True
    from django.contrib.auth import get_user_model
    from django.contrib.contenttypes.models import ContentType

    from groups.models.group import Group
    from groups.models.membership import GroupMembership

    profile = ensure_user_profile(user)
    sponsor_ct = initiative.sponsor_content_type_id
    oid = initiative.sponsor_object_id
    if sponsor_ct == ContentType.objects.get_for_model(type(profile)).id and str(oid) == str(profile.pk):
        return True
    User = get_user_model()
    if sponsor_ct == ContentType.objects.get_for_model(User).id and str(oid) == str(user.pk):
        return True
    if sponsor_ct == ContentType.objects.get_for_model(Group).id:
        return GroupMembership.objects.filter(
            group_id=oid,
            member_content_type=ContentType.objects.get_for_model(User),
            member_object_id=user.id,
            deleted_at__isnull=True,
        ).exists()
    return False


def _open_in_initiative(profile, initiative):
    """The person's most recent Dialogue in an Initiative, or a new one. Returns (dialogue, created)."""
    from django.contrib.contenttypes.models import ContentType

    from groups.models.group import Group

    dialogue = (
        Dialogue.objects.filter(member=profile, initiative=initiative, deleted_at__isnull=True)
        .order_by(F("last_activity_at").desc(nulls_last=True), "-created_at")
        .first()
    )
    if dialogue is not None:
        return dialogue, False
    group_ct = ContentType.objects.get_for_model(Group)
    is_group = initiative.sponsor_content_type_id == group_ct.id
    dialogue = Dialogue.objects.create(
        member=profile,
        initiative=initiative,
        sponsor_content_type=group_ct if is_group else None,
        sponsor_object_id=initiative.sponsor_object_id if is_group else None,
    )
    return dialogue, True


class InitiativeOpenView(APIView):
    """
    POST /api/atrium/initiatives/<initiative_id>/open

    Open an Initiative in Atrium: the person's most recent Dialogue in it, or a new one
    when there is none. There is no Dialogue Zero (CTO, 2026-11-04): Dialogues stay
    light, and the first gets the ball rolling. Returns the Dialogue (201 when new).
    (Also served at the old .../dialogue-zero path until the page is deployed.)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, initiative_id):
        from initiatives.models import Initiative

        initiative = Initiative.objects.filter(id=initiative_id, deleted_at__isnull=True).first()
        if initiative is None or not _can_open_initiative(request.user, initiative):
            return Response({"detail": "Initiative not found."}, status=status.HTTP_404_NOT_FOUND)

        dialogue, created = _open_in_initiative(ensure_user_profile(request.user), initiative)
        return Response(
            DialogueListSerializer(dialogue).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class DialogueMemoryView(APIView):
    """
    GET / PATCH /api/atrium/dialogues/<dialogue_id>/memory  { memory }

    The memory of the Initiative this Dialogue belongs to: every Dialogue in the
    Initiative opens with it (design-st3b §13). 422 when the Dialogue has no Initiative.
    """

    permission_classes = [IsAuthenticated]

    def _log(self, request, dialogue_id):
        from atrium.ai.service import _resolve_initiative_log

        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return None, _not_found()
        log, _ = _resolve_initiative_log(dialogue)
        if log is None:
            return None, Response(
                {"detail": "This Dialogue has no Initiative to keep a memory in."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return log, None

    def _body(self, log):
        initiative = log.initiative
        return {
            "initiative_id": str(initiative.id),
            "initiative_title": initiative.title,
            "initiative_is_personal": bool(initiative.is_personal),
            "memory": log.memory,
        }

    def get(self, request, dialogue_id):
        log, stop = self._log(request, dialogue_id)
        return stop or Response(self._body(log))

    def patch(self, request, dialogue_id):
        log, stop = self._log(request, dialogue_id)
        if stop:
            return stop
        log.memory = (request.data.get("memory") or "").strip()
        log.save(update_fields=["memory", "updated_at"])
        return Response(self._body(log))


class DialogueEntryListView(generics.ListAPIView):
    """
    GET /api/atrium/dialogues/<dialogue_id>/entries/

    The Dialogue's entries in order, including any reply still being written
    (status pending or streaming: follow it with .../entries/<id>/stream).
    """

    permission_classes = [IsAuthenticated]
    serializer_class = DialogueEntrySerializer

    def get_queryset(self):
        profile = ensure_user_profile(self.request.user)
        return DialogueEntry.objects.filter(
            dialogue_id=self.kwargs["dialogue_id"],
            dialogue__member=profile,
            dialogue__deleted_at__isnull=True,
        ).order_by("created_at")


class DialogueEntryStreamView(APIView):
    """
    GET /api/atrium/dialogues/<dialogue_id>/entries/<entry_id>/stream

    Follow a reply that is still being written: after a reload, or from another
    device. Same events as the exchange stream, from the start of the reply.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, dialogue_id, entry_id):
        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return _not_found()
        entry = DialogueEntry.objects.filter(pk=entry_id, dialogue=dialogue).first()
        if entry is None:
            return Response({"detail": "Entry not found."}, status=status.HTTP_404_NOT_FOUND)
        opening = {"type": "turn", "entry_id": str(entry.id), "speaker": entry.speaker}
        return StreamingHttpResponse(
            follow_reply(entry.id, opening=opening),
            content_type="text/event-stream",
            headers=_SSE_HEADERS,
        )


class DialogueInitiativeLogView(APIView):
    """
    GET /api/atrium/dialogues/<dialogue_id>/initiative-log/

    InitiativeLogEntry records (prose + ledger) for the Dialogue's Initiative.
    Returns [] when the Dialogue has no Initiative.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, dialogue_id):
        from initiatives.models import InitiativeLogEntry

        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return _not_found()
        if not dialogue.initiative_id:
            return Response({"results": []})

        entries = InitiativeLogEntry.objects.filter(
            initiative_log__initiative_id=dialogue.initiative_id,
        ).order_by("created_at").values(
            "id", "kind", "body", "authored_by",
            "source_turn_index", "source_timestamp", "created_at",
            "ledger_event_type", "ledger_data",
        )
        return Response({"results": list(entries)})


class DialogueContextView(APIView):
    """
    GET /api/atrium/dialogues/<dialogue_id>/context/

    The Clio personal context an agent is given in this Dialogue, as a preview:
    transparent about what the agent knows. Response: { context, sources }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, dialogue_id):
        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return _not_found()

        from atrium.ai.context import ClioPersonalContextBuilder
        builder = ClioPersonalContextBuilder()
        return Response({"context": builder.build(dialogue), "sources": builder.sources(dialogue)})


class DialogueUpdateView(APIView):
    """
    PATCH /api/atrium/dialogues/<dialogue_id>/

    Body: { title?, session_context?, dial_mode?, ai_provider? }
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, dialogue_id):
        from atrium.turns import DIALOGUE_PROVIDERS

        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return _not_found()

        update_fields = []
        if "title" in request.data:
            dialogue.title = request.data["title"]
            update_fields.append("title")
        if "session_context" in request.data:
            dialogue.session_context = request.data["session_context"]
            update_fields.append("session_context")
        if "dial_mode" in request.data and request.data["dial_mode"] in {m.value for m in AtriumDialMode}:
            dialogue.dial_mode = request.data["dial_mode"]
            update_fields.append("dial_mode")
        if "ai_provider" in request.data and request.data["ai_provider"] in DIALOGUE_PROVIDERS:
            dialogue.ai_provider = request.data["ai_provider"]
            update_fields.append("ai_provider")

        if update_fields:
            dialogue.save(update_fields=update_fields + ["updated_at"])

        return Response(DialogueListSerializer(dialogue).data, status=status.HTTP_200_OK)


class DialogueExchangeView(APIView):
    """
    POST /api/atrium/dialogues/<dialogue_id>/exchange

    Body: { message, provider? } — provider is anthropic-claude-code or openai-codex
    (default: the Dialogue's last). Saves the message, queues the reply on the runtime
    worker, and streams it as it is written: text/event-stream with turn, delta,
    final, done, or error {code, detail}.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, dialogue_id):
        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return _not_found()
        return _exchange_response(request, dialogue)


class DialogueWarmView(APIView):
    """
    POST /api/atrium/dialogues/<dialogue_id>/warm

    Nothing to warm: each turn starts its own process (ST-3 Part B). Kept so the page
    can call it on open; returns a single `ready` event.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, dialogue_id):
        if _own_dialogue(request, dialogue_id) is None:
            return _not_found()
        return StreamingHttpResponse(
            iter([_sse({"type": "ready"})]),
            content_type="text/event-stream",
            headers=_SSE_HEADERS,
        )


class DialogueCompactView(APIView):
    """
    POST /api/atrium/dialogues/<dialogue_id>/compact

    Compact (ST-3 Part B step 4): add a checkpoint entry, the Dialogue so far
    summarized on the owner's own account by the runtime worker. Later turns start
    fresh provider sessions from it. Returns 202 { status: "queued", entry_id };
    follow it with entries/<entry_id>/stream.

    PATCH /api/atrium/dialogues/<dialogue_id>/compact { entry_id, content }
    Edit a finished checkpoint; the next turn uses the edited text.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, dialogue_id):
        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return _not_found()
        from atrium import relay
        from atrium.models import DialogueEntryType, DialogueRole
        from atrium.tasks import run_compact

        busy = dialogue.entries.filter(
            status__in=[DialogueEntryStatus.PENDING, DialogueEntryStatus.STREAMING]
        ).exists()
        if busy:
            return Response(
                {"detail": "Wait for the reply in progress to finish."},
                status=status.HTTP_409_CONFLICT,
            )
        entry = DialogueEntry.objects.create(
            dialogue=dialogue,
            role=DialogueRole.ASSISTANT,
            entry_type=DialogueEntryType.CHECKPOINT,
            status=DialogueEntryStatus.PENDING,
        )
        relay.notify(entry.id)
        run_compact.delay(str(entry.id))
        return Response({"status": "queued", "entry_id": str(entry.id)}, status=status.HTTP_202_ACCEPTED)

    def patch(self, request, dialogue_id):
        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return _not_found()
        from atrium.models import DialogueEntryType

        content = (request.data.get("content") or "").strip()
        entry = dialogue.entries.filter(
            pk=request.data.get("entry_id"),
            entry_type=DialogueEntryType.CHECKPOINT,
            status=DialogueEntryStatus.DONE,
        ).first()
        if entry is None:
            return _not_found()
        if not content:
            return Response({"detail": "A checkpoint can't be empty."}, status=status.HTTP_400_BAD_REQUEST)
        entry.content = content
        entry.save(update_fields=["content", "updated_at"])
        return Response({"status": "saved", "entry_id": str(entry.id)})


class DialogueDistillView(APIView):
    """
    POST /api/atrium/dialogues/<dialogue_id>/distill

    Body: { title, document_type }. Creates the Distillate pending and writes it on the
    runtime worker, on the owner's account. Returns 202 with the Distillate; poll
    GET .../distillates/<id> until status is done or failed.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, dialogue_id):
        from atrium.ai.service import _resolve_initiative_log
        from atrium.turns import TurnStop, owner_runtime
        from cloud_agents.constants import PROVIDER_ANTHROPIC_CLAUDE_CODE

        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return _not_found()

        title = (request.data.get("title") or "").strip()
        document_type = request.data.get("document_type") or DistillateDocumentType.SUMMARY
        if not title:
            return Response({"detail": "title is required."}, status=status.HTTP_400_BAD_REQUEST)
        if document_type not in DistillateDocumentType.values:
            return Response(
                {"detail": f"document_type must be one of: {', '.join(DistillateDocumentType.values)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        log, _ = _resolve_initiative_log(dialogue)
        if log is None:
            return Response(
                {"detail": "No Initiative found for this Dialogue — a Distillate needs one."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if not dialogue.entries.filter(status=DialogueEntryStatus.DONE).exists():
            return Response({"detail": "This Dialogue has nothing to distill yet."}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        distillate = Distillate.objects.create(
            initiative=log.initiative,
            dialogue=dialogue,
            title=title,
            document_type=document_type,
            status=DistillateStatus.PENDING,
        )
        try:
            owner_runtime(dialogue, PROVIDER_ANTHROPIC_CLAUDE_CODE)
        except TurnStop as stop:
            distillate.status = DistillateStatus.FAILED
            distillate.error_code = stop.code
            distillate.save(update_fields=["status", "error_code"])
            data = DistillateSerializer(distillate).data
            data["detail"] = REPLY_STOP_MESSAGES.get(stop.code, REPLY_STOP_MESSAGES["failed"])
            return Response(data, status=status.HTTP_409_CONFLICT)

        from atrium.tasks import run_distill
        run_distill.apply_async(kwargs={"distillate_id": str(distillate.id)}, queue="runtime", routing_key="runtime")
        logger.info("atrium_distill dialogue=%s distillate=%s type=%s", dialogue.id, distillate.id, document_type)
        return Response(DistillateSerializer(distillate).data, status=status.HTTP_202_ACCEPTED)


class DialogueDistillateView(APIView):
    """GET /api/atrium/dialogues/<dialogue_id>/distillates/<distillate_id> — poll a Distillate."""

    permission_classes = [IsAuthenticated]

    def get(self, request, dialogue_id, distillate_id):
        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return _not_found()
        distillate = Distillate.objects.filter(pk=distillate_id, dialogue=dialogue).first()
        if distillate is None:
            return Response({"detail": "Distillate not found."}, status=status.HTTP_404_NOT_FOUND)
        data = DistillateSerializer(distillate).data
        if distillate.status == DistillateStatus.FAILED:
            data["detail"] = REPLY_STOP_MESSAGES.get(distillate.error_code, REPLY_STOP_MESSAGES["failed"])
        return Response(data)


class DialogueResetView(APIView):
    """
    POST /api/atrium/dialogues/<dialogue_id>/reset

    Start every agent fresh in this Dialogue: their own sessions are dropped, and the
    next turn opens with the Dialogue's own record. Entries are kept.
    Returns { status: "ready" }.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, dialogue_id):
        dialogue = _own_dialogue(request, dialogue_id)
        if dialogue is None:
            return _not_found()
        CloudAgentSession.objects.filter(dialogue=dialogue, deleted_at__isnull=True).update(
            provider_session_id="", seen_through=None, status="starting",
        )
        logger.info("atrium_reset dialogue=%s user=%s", dialogue.id, request.user.username)
        return Response({"status": "ready"}, status=status.HTTP_200_OK)


def _personal_dialogue(profile):
    dialogue = (
        Dialogue.objects.filter(
            member=profile,
            sponsor_object_id__isnull=True,
            status=DialogueStatus.ACTIVE,
            deleted_at__isnull=True,
        )
        .order_by(F("last_activity_at").desc(nulls_last=True), "-created_at")
        .first()
    )
    if dialogue is None:
        from atrium.initiative_zero import initiative_zero

        dialogue = Dialogue.objects.create(
            member=profile, title="", session_context="", initiative=initiative_zero(profile.user)
        )
    return dialogue


class AtriumStartView(APIView):
    """
    GET /api/atrium/me/start

    Where personal Atrium opens: the member's most recently active Dialogue outside a
    Group, so the Initiative last worked in; else Initiative Zero's most recent
    Dialogue, or a new one there (CTO, 2026-11-04).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from atrium.initiative_zero import initiative_zero

        profile = ensure_user_profile(request.user)
        dialogue = (
            Dialogue.objects.filter(member=profile, sponsor_object_id__isnull=True, deleted_at__isnull=True)
            .order_by(F("last_activity_at").desc(nulls_last=True), "-created_at")
            .first()
        )
        if dialogue is None:
            dialogue, _ = _open_in_initiative(profile, initiative_zero(request.user))
        return Response(DialogueListSerializer(dialogue).data, status=status.HTTP_200_OK)


class AtriumMeDialogueView(APIView):
    """
    GET /api/atrium/me/dialogue

    The member's personal Dialogue (no sponsor), created if none is active.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        dialogue = _personal_dialogue(ensure_user_profile(request.user))
        return Response(DialogueListSerializer(dialogue).data, status=status.HTTP_200_OK)


class AtriumMeDialogueExchangeView(APIView):
    """
    POST /api/atrium/me/dialogue/exchange

    The exchange on the member's personal Dialogue; same body and events as
    /dialogues/<id>/exchange.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        dialogue = _personal_dialogue(ensure_user_profile(request.user))
        return _exchange_response(request, dialogue)


class AtriumSponsorContextView(APIView):
    """
    GET /api/atrium/sponsor-context/

    Returns sponsor identity + lightweight initiative list + recent Atrium
    MillDrafts for the current Atrium surface (personal or group-scoped).

    Query params:
      group_slug — if provided, returns context for that group's Atrium.
                   Requires the requesting user to be an active group member.
                   If absent, returns the personal (user-sponsored) context.

    Response:
      {
        sponsor_type: "user" | "group",
        sponsor_slug: str,
        sponsor_name: str,
        sponsor_id: str,
        initiatives: [{id, title, status}],
        recent_drafts: [{id, title, created_at}],
      }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType

        group_slug = request.query_params.get("group_slug", "")

        if group_slug:
            from groups.models.group import Group
            from groups.models.membership import GroupMembership

            group = Group.objects.filter(slug=group_slug, deleted_at__isnull=True).first()
            if not group:
                return Response({"detail": "Group not found."}, status=status.HTTP_404_NOT_FOUND)

            User = get_user_model()
            user_ct = ContentType.objects.get_for_model(User)
            is_member = GroupMembership.objects.filter(
                group_id=group.pk,
                member_content_type=user_ct,
                member_object_id=request.user.id,
                deleted_at__isnull=True,
            ).exists()
            if not is_member and not request.user.is_staff:
                return Response({"detail": "Not a member of this group."}, status=status.HTTP_403_FORBIDDEN)

            sponsor_ct = ContentType.objects.get_for_model(Group)
            sponsor_id = group.pk

            from initiatives.models import Initiative
            initiatives_qs = Initiative.objects.filter(
                sponsor_content_type=sponsor_ct,
                sponsor_object_id=sponsor_id,
                parent__isnull=True,
                deleted_at__isnull=True,
            ).exclude(status__in=["resolved", "archived"]).order_by("-updated_at").values("id", "title", "status")[:10]

            sponsor_data = {
                "sponsor_type": "group",
                "sponsor_slug": group.slug,
                "sponsor_name": group.title,
                "sponsor_id": str(sponsor_id),
            }

        else:
            User = get_user_model()
            user = request.user
            user_ct = ContentType.objects.get_for_model(User)
            sponsor_ct = user_ct
            sponsor_id = user.pk

            from initiatives.models import Initiative
            initiatives_qs = Initiative.objects.filter(
                sponsor_content_type=sponsor_ct,
                sponsor_object_id=sponsor_id,
                deleted_at__isnull=True,
            ).exclude(status__in=["resolved", "archived"]).order_by("-updated_at").values("id", "title", "status")[:10]

            sponsor_data = {
                "sponsor_type": "user",
                "sponsor_slug": user.username,
                "sponsor_name": user.get_full_name() or user.username,
                "sponsor_id": str(sponsor_id),
            }

        from fundamentals.models_milldraft import MillDraft
        recent_drafts = list(
            MillDraft.objects.filter(
                sponsor_content_type=sponsor_ct,
                sponsor_object_id=sponsor_id,
                source_type="atrium",
                deleted_at__isnull=True,
            ).order_by("-created_at").values("id", "title", "created_at")[:5]
        )

        return Response({
            **sponsor_data,
            "initiatives": list(initiatives_qs),
            "recent_drafts": [
                {"id": str(d["id"]), "title": d["title"], "created_at": d["created_at"].isoformat()}
                for d in recent_drafts
            ],
        })
