# initiatives/services/findings.py
#
# ADR-0064 D6: Argus findings are a structured Artifact, validated like any
# other shaped record. The Shape itself (argus.findings) is drafted in
# Contour and carried here via the Contour bundle (heddle.bundle) -- Contour
# is the source, this never duplicates or hand-checks its schema.
#
# One rule from the Shape's own `rules` is deliberately NOT enforced here:
# "each finding's type must be one of the block's declared finding types"
# is explicitly marked "validation step, not the schema" in
# findings.shape.yaml, and a block's declared finding_types live in its
# Puddlejump frontmatter, which core has no read path to today. Tracked as
# an open gap, not silently skipped: see the module docstring reference in
# this file's own commit message.

from __future__ import annotations

from jsonschema import ValidationError as ShapeValidationError

from heddle.bundle import validate_shaped_payload
from initiatives.models import ActionRun, Artifact, ArtifactKind


class FindingsShapeError(ValueError):
    """The payload failed argus.findings validation."""


def create_findings_artifact(*, action_run: ActionRun, payload: dict) -> Artifact:
    """
    Validate `payload` against its own declared Shape (argus.findings) and
    store it as a FINDINGS Artifact on action_run.initiative, linked back to
    the run. Raises FindingsShapeError on an invalid payload -- the run
    still has to write its Artifact or record why it couldn't (ADR-0064
    §4.1); a validation failure is the caller's problem to handle, not
    swallowed here.
    """
    try:
        validate_shaped_payload(payload)
    except ShapeValidationError as exc:
        raise FindingsShapeError(str(exc)) from exc

    return Artifact.objects.create(
        initiative=action_run.initiative,
        action_run=action_run,
        kind=ArtifactKind.FINDINGS,
        title=f"{payload['block_id']} findings ({payload['outcome']})",
        shape_id=payload["shape_id"],
        shape_version=payload["shape_version"],
        structured_data=payload,
    )
