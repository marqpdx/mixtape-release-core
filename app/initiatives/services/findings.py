# initiatives/services/findings.py
#
# ADR-0064 D6: Argus findings are a structured Artifact, validated like any
# other shaped record. The Shape itself (argus.findings) is drafted in
# Contour and carried here via the Contour bundle (heddle.bundle) -- Contour
# is the source, this never duplicates or hand-checks its schema.
#
# One rule from the Shape's own `rules` is schema-adjacent, not
# schema-enforceable: "each finding's type must be one of the block's
# declared finding types". Checked here via surfaces.services.argus_blocks,
# best-effort -- when PUDDLEJUMP_PATH isn't configured (today's reality on
# Crossroads; see that module's docstring), the check is skipped rather than
# failing every findings Artifact over an unrelated unavailability.

from __future__ import annotations

from jsonschema import ValidationError as ShapeValidationError

from heddle.bundle import validate_shaped_payload
from initiatives.models import ActionRun, Artifact, ArtifactKind
from surfaces.services.argus_blocks import read_audit_block


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

    block, unavailable_reason = read_audit_block(payload["block_id"])
    if not unavailable_reason and block is not None:
        declared = set(block.finding_types)
        if declared:
            undeclared = {f["type"] for f in payload["findings"]} - declared
            if undeclared:
                raise FindingsShapeError(
                    f"Undeclared finding type(s) for block '{block.slug}': {sorted(undeclared)}"
                )

    return Artifact.objects.create(
        initiative=action_run.initiative,
        action_run=action_run,
        kind=ArtifactKind.FINDINGS,
        title=f"{payload['block_id']} findings ({payload['outcome']})",
        shape_id=payload["shape_id"],
        shape_version=payload["shape_version"],
        structured_data=payload,
    )
