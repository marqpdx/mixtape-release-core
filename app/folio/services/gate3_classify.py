# folio/services/gate3_classify.py
#
# Gate 3 — materiality classification (prototype spec §8-9). Input: raw
# text, Gate 1's candidate spans. The model decides material/not-material
# per candidate and picks a reason code, addressed by Gate 1's own label
# (a, b, c, ...) rather than by offsets — start/end for each decision is
# looked up deterministically from Gate 1's output afterward, never trusted
# from the model, same rationale as Gate 2's offset handling.

from inkwell.client import InkwellUnavailableError, service_generate

REASON_CODES = [
    "explicit_enumerated_idea",
    "explicit_named_item",
    "explicit_question",
    "explicit_need",
    "explicit_example",
    "clear_discourse_distinction",
    "not_material_connective",
    "not_material_repetition",
    "uncertain_keep_attached",
]

GATE3_SYSTEM = (
    "You are a materiality assessor inside a writing-craft tool. You identify "
    "distinctions the writer has already expressed that may be worth shaping "
    "independently. You do not improve the writing. You do not create an "
    "outline. You do not invent categories. You do not infer a thesis. You do "
    "not split text merely because you can. You prefer the smallest amount of "
    "structure that faithfully reflects the writer's expressed distinctions. "
    "Mark a span as materially distinct when there is evidence the writer is "
    "treating it as a separate idea, question, need, example, or other unit "
    "of attention. Explicit writer signals outrank semantic inference. When "
    "uncertain, keep material together. Return only source-grounded decisions "
    "and machine-readable reason codes, never prose."
)


def _build_user_prompt(raw_text: str, candidates: list[dict]) -> str:
    candidate_lines = "\n".join(
        f'- {c["label"]}) "{c["text"]}"' for c in candidates
    )
    return (
        "Text:\n" + raw_text + "\n\n"
        "Candidate spans (from deterministic parsing):\n" + candidate_lines + "\n\n"
        "For each candidate, decide only: does this appear to be a materially "
        "distinct thought the writer presented as worth separate attention? "
        "Return one decision per candidate label, addressed by its label."
    )


def _build_schema(candidates: list[dict]) -> dict:
    return {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "enum": [c["label"] for c in candidates]},
                        "material": {"type": "boolean"},
                        "reason_code": {"type": "string", "enum": REASON_CODES},
                    },
                    "required": ["label", "material", "reason_code"],
                },
            },
        },
        "required": ["decisions"],
    }


def classify_gate3(raw_text: str, gate1_output: dict) -> dict:
    """
    Returns {"items": [{"source_start", "source_end", "material", "reason_code"}],
    "method": str|None}. Raises InkwellUnavailableError if Inkwell can't be
    reached — callers decide how to degrade.

    No enumerations from Gate 1 means nothing to classify — returns an empty
    item list without calling the model, per "under-extraction preferred".
    """
    enumerations = gate1_output.get("enumerations") or []
    if not enumerations:
        return {"items": [], "method": None}

    candidates = [
        {
            "label": e["label"],
            "start": e["start"],
            "end": e["end"],
            "text": raw_text[e["start"]:e["end"]],
        }
        for e in enumerations
    ]

    result = service_generate(
        system_prompt=GATE3_SYSTEM,
        prompt=_build_user_prompt(raw_text, candidates),
        schema=_build_schema(candidates),
        max_tokens=300,
        temperature=0.0,
    )
    parsed = result.get("result") or {}
    decisions = parsed.get("decisions") or []

    by_label = {c["label"]: c for c in candidates}
    items = []
    for decision in decisions:
        label = decision.get("label")
        candidate = by_label.get(label)
        if candidate is None:
            continue
        items.append({
            "source_start": candidate["start"],
            "source_end": candidate["end"],
            "material": bool(decision.get("material")),
            "reason_code": decision.get("reason_code"),
        })

    return {"items": items, "method": result.get("method")}
