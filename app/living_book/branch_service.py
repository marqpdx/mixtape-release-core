from __future__ import annotations

from django.db import transaction

from .models import Branch, LeafCluster, LivingBook


def _is_dispatch_collaborator(user, living_book: LivingBook) -> bool:
    """True if user is the trunk author or a Dispatch collaborator on the trunk."""
    trunk = living_book.trunk
    if trunk.author_id == user.pk:
        return True
    try:
        from dispatch.models import DispatchContent
    except ImportError:
        return False
    dc = DispatchContent.objects.filter(writing_piece=trunk).first()
    if dc is None:
        return False
    return dc.collaborators.filter(user=user).exists()


class BranchService:

    @staticmethod
    @transaction.atomic
    def create_branch(
        living_book: LivingBook,
        anchor_node_id,
        *,
        created_by,
        prompt_text: str | None = None,
        due_date=None,
    ) -> Branch:
        branch = Branch.objects.create(
            living_book=living_book,
            anchor_node_id=anchor_node_id,
            prompt_text=prompt_text or None,
            due_date=due_date,
            parent_branch=None,  # v1 invariant: trunk-level only
            is_detached=False,
            created_by=created_by,
        )
        from . import producers
        producers.on_branch_created(branch)
        return branch

    @staticmethod
    @transaction.atomic
    def update_branch(
        branch: Branch,
        *,
        prompt_text: str | None = ...,
        due_date=...,
        is_detached: bool | None = None,
    ) -> Branch:
        if prompt_text is not ...:
            branch.prompt_text = prompt_text or None
        if due_date is not ...:
            branch.due_date = due_date
        if is_detached is not None:
            branch.is_detached = is_detached
        branch.save()
        return branch

    @staticmethod
    @transaction.atomic
    def send_invitation(branch: Branch, *, sent_by) -> None:
        if not branch.prompt_text:
            raise ValueError("Cannot send invitation: prompt_text is empty.")
        from . import producers
        producers.on_prompt_sent(branch, sent_by=sent_by)

    @staticmethod
    @transaction.atomic
    def delete_branch(branch: Branch) -> None:
        if branch.leaf_clusters.exists():
            count = branch.leaf_clusters.count()
            raise ValueError(
                f"Cannot delete branch: {count} leaf cluster(s) attached. Detach them first."
            )
        branch.delete()


class LeafClusterService:

    @staticmethod
    @transaction.atomic
    def attach_piece(
        branch: Branch,
        piece_slug: str,
        *,
        created_by,
        media_type: str = LeafCluster.MEDIA_TEXT,
    ) -> LeafCluster:
        if media_type == LeafCluster.MEDIA_VIDEO:
            raise ValueError("Video leaf-clusters are not yet supported.")

        from writing.models import WritingPiece
        from django.shortcuts import get_object_or_404
        piece = get_object_or_404(WritingPiece, slug=piece_slug)

        if LeafCluster.objects.filter(branch=branch, piece=piece).exists():
            raise ValueError("This piece is already attached to this branch.")

        lc = LeafCluster.objects.create(
            branch=branch,
            piece=piece,
            media_type=media_type,
            created_by=created_by,
        )
        from . import producers
        producers.on_leaf_cluster_attached(lc)
        return lc

    @staticmethod
    @transaction.atomic
    def detach_piece(leaf_cluster: LeafCluster) -> None:
        leaf_cluster.delete()
