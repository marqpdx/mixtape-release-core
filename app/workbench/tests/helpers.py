import uuid

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from feedback.models import FeedbackBeacon, FeedbackItem
from fundamentals.models import MillDraft, MillDraftStatus
from groups.models.group import Group, GroupType
from groups.models.membership import GroupMembership
from workbench.models import WorkingItem, WorkingItemStatus
from writing.models import Seed, WorkingDocument, WritingPiece
from commons.models import Leaf


User = get_user_model()


def body_json(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def create_group(*, sponsor_user: User, title: str, slug: str) -> Group:
    group = Group(
        title=title,
        slug=slug,
        description="Test group",
        group_type=GroupType.COMMUNITY,
    )
    group.set_sponsor(sponsor_user)
    group.set_submitted_by(sponsor_user)
    group.author = sponsor_user
    group.author_name = sponsor_user.get_full_name() or sponsor_user.username
    group.save()
    return group


def add_group_member(*, group: Group, user: User, roles: list[str] | None = None) -> GroupMembership:
    user_ct = ContentType.objects.get_for_model(User)
    return GroupMembership.objects.create(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.id,
        roles=roles or ["member"],
        is_active=True,
    )


def create_seed(*, author: User, body_text: str = "", transcript_text: str | None = None, status: str = "ready") -> Seed:
    return Seed.objects.create(
        author=author,
        body_text=body_text,
        transcript_text=transcript_text,
        status=status,
    )


def create_leaf(*, author: User, body_text: str, kind: str = "text") -> Leaf:
    return Leaf.objects.create(
        author=author,
        body_text=body_text,
        kind=kind,
    )


def create_milldraft(*, author: User, sponsor, title: str, grist_body: str, status: str = MillDraftStatus.CANDIDATE) -> MillDraft:
    sponsor_ct = ContentType.objects.get_for_model(sponsor)
    draft = MillDraft(
        author=author,
        author_name=author.get_full_name() or author.username,
        submitted_by=author,
        sponsor_content_type=sponsor_ct,
        sponsor_object_id=sponsor.pk,
        title=title,
        content_profile="writing",
        grist_body=grist_body,
        status=status,
    )
    draft.save()
    return draft


def create_writing_piece(*, author: User, sponsor, title: str, status: str = "draft") -> WritingPiece:
    piece = WritingPiece(
        author=author,
        author_name=author.get_full_name() or author.username,
        submitted_by=author,
        title=title,
        excerpt=f"{title} excerpt",
        body_json=body_json(f"{title} body"),
        writing_kind="post",
        status=status,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
    )
    piece.set_sponsor(sponsor)
    piece.save()
    return piece


def create_working_document(*, user: User, piece: WritingPiece, title: str, text: str) -> WorkingDocument:
    return WorkingDocument.objects.create(
        piece=piece,
        user=user,
        title=title,
        body_json=body_json(text),
    )


def create_feedback(*, user: User, message: str, status: str = FeedbackItem.Status.NEW) -> FeedbackItem:
    beacon = FeedbackBeacon.objects.create(
        key=f"wb-{uuid.uuid4().hex[:8]}",
        title="Workbench Beacon",
    )
    return FeedbackItem.objects.create(
        beacon=beacon,
        kind=FeedbackItem.Kind.IDEA,
        message=message,
        user=user,
        status=status,
    )


def create_working_item(
    *,
    group: Group,
    author: User,
    title: str = "Working Item",
    status: str = WorkingItemStatus.ASSEMBLING,
    spellcheck_passed: bool = False,
    body_editing_started: bool = False,
    body: str = "",
) -> WorkingItem:
    item = WorkingItem(
        author=author,
        author_name=author.get_full_name() or author.username,
        submitted_by=author,
        title=title,
        status=status,
        spellcheck_passed=spellcheck_passed,
        body_editing_started=body_editing_started,
        body_json=body_json(body) if body else {},
    )
    item.set_sponsor(group)
    item.save()
    return item
