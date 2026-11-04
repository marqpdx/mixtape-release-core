"""Exact cue/mention scoring with inspectable boundary/type/qualifier errors."""
from collections import Counter

from adapter import digest, text_hash, validate_request, validate_response
from recognition import exact_span_scores


def score_rows(rows):
    return [{"source_ref": (r["source_ref"], r["source_revision"]), "label": r["type"],
             "start": r["start"], "end": r["end"]} for r in rows]


def errors(predicted, gold):
    def key(r):
        return r["source_ref"], r["source_revision"], r["type"], r["start"], r["end"]
    remaining = Counter(key(r) for r in gold)
    unmatched = []
    for row in predicted:
        if remaining[key(row)]:
            remaining[key(row)] -= 1
        else:
            unmatched.append(row)
    missing = []
    for row in gold:
        if remaining[key(row)]:
            missing.append(row)
            remaining[key(row)] -= 1
    type_errors, boundary_errors = [], []
    for row in unmatched:
        nearby = [g for g in missing if (g["source_ref"], g["source_revision"]) == (row["source_ref"], row["source_revision"])]
        for expected in nearby:
            if (row["start"], row["end"]) == (expected["start"], expected["end"]) and row["type"] != expected["type"]:
                type_errors.append({"predicted": row, "expected": expected})
            elif row["type"] == expected["type"] and max(row["start"], expected["start"]) < min(row["end"], expected["end"]):
                boundary_errors.append({"predicted": row, "expected": expected})
    return {"false_positives": unmatched, "false_negatives": missing,
            "type_errors": type_errors, "boundary_errors": boundary_errors}


def row_key(row):
    return row["source_ref"], row["source_revision"], row["type"], row["start"], row["end"]


def neutral_optional(predicted, gold, optional_gold):
    """Required matches first; one exact optional hit is neutral. Duplicates remain FP."""
    required = Counter(row_key(r) for r in gold)
    optional = Counter(row_key(r) for r in optional_gold)
    scored, hits = [], []
    for row in predicted:
        key = row_key(row)
        if required[key]:
            required[key] -= 1
            scored.append(row)
        elif optional[key]:
            optional[key] -= 1
            hits.append(row)
        else:
            scored.append(row)
    return scored, hits


def overlap_scores(predicted, gold):
    """Maximum one-to-one same-type overlap matching; supplemental to exact spans."""
    edges = [[j for j, g in enumerate(gold) if
              (r["source_ref"], r["source_revision"], r["type"]) == (g["source_ref"], g["source_revision"], g["type"])
              and max(r["start"], g["start"]) < min(r["end"], g["end"])] for r in predicted]
    matched = {}
    def augment(index, seen):
        for target in edges[index]:
            if target in seen:
                continue
            seen.add(target)
            if target not in matched or augment(matched[target], seen):
                matched[target] = index
                return True
        return False
    tp = sum(augment(i, set()) for i in range(len(predicted)))
    fp, fn = len(predicted) - tp, len(gold) - tp
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def summarize(predicted, gold, optional_gold=None):
    optional_gold = optional_gold or []
    predicted, hits = neutral_optional(predicted, gold, optional_gold)
    labels = sorted({r["type"] for r in predicted + gold})
    return {"micro": exact_span_scores(score_rows(predicted), score_rows(gold)),
            "per_type": {label: exact_span_scores(score_rows([r for r in predicted if r["type"] == label]),
                                                   score_rows([r for r in gold if r["type"] == label])) for label in labels},
            "relaxed_overlap_micro": overlap_scores(predicted, gold),
            "relaxed_overlap_per_type": {label: overlap_scores([r for r in predicted if r["type"] == label],
                                                               [r for r in gold if r["type"] == label]) for label in labels},
            "optional": {"gold_count": len(optional_gold), "hit_count": len(hits), "hits": hits},
            **errors(predicted, gold)}


def evaluate(cases, responses, split):
    cases = list(cases)
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate dataset case id")
    selected = [c for c in cases if c["split"] == split]
    if not selected:
        raise ValueError("Selected split has no cases")
    requests = {}
    for case in selected:
        request = case["request"]
        validate_request(request)
        if (case["source_sha256"] != text_hash(request["source"]["text"]) or
                case["annotation_digest"] != digest(case["annotations"])):
            raise ValueError("Case source/annotation integrity mismatch")
        text = request["source"]["text"]
        spans = [a for kind in ("cues", "mentions", "traps", "ambiguities") for a in case["annotations"].get(kind, [])]
        spans += [a for j in case["annotations"]["shape_judgements"] for a in j["evidence"]]
        for span in spans:
            start, end = span["start"], span["end"]
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or
                    text[start:end] != span["quote"]):
                raise ValueError("Invalid gold code-point annotation")
        ref = request["source"]["source_ref"]
        if ref in requests:
            raise ValueError("Duplicate source identity")
        requests[ref] = case
    output = {}
    for response in responses:
        ref = response.get("source_ref")
        if ref not in requests or ref in output:
            raise ValueError("Unknown, duplicate or wrong-split adapter response")
        validate_response(requests[ref]["request"], response)
        output[ref] = response
    if output.keys() != requests.keys():
        raise ValueError("Missing adapter response: failures must not become empty predictions")
    pools = {kind: {"predicted": [], "gold": [], "optional_gold": []} for kind in ("cue", "mention")}
    qualifier_errors, ordinary_false_positives = [], []
    for ref, case in requests.items():
        revision = case["request"]["source"]["source_revision"]
        for kind in pools:
            for candidate in output[ref]["candidates"]:
                if candidate["candidate_kind"] != kind:
                    continue
                loc = candidate["source_locator"]
                row = {"source_ref": ref, "source_revision": revision, "type": candidate["type"],
                       "start": loc["start"], "end": loc["end"], "quote": loc["quote"]}
                pools[kind]["predicted"].append(row)
                for trap in case["annotations"]["traps"]:
                    overlaps = max(trap["start"], loc["start"]) < min(trap["end"], loc["end"])
                    if overlaps and (kind == "mention" or not (candidate["ambiguous"] or candidate["negated"])):
                        ordinary_false_positives.append({"candidate": row, "reason": trap["reason"]})
                if kind == "cue":
                    expected = [g for g in case["annotations"]["cues"] if (g["start"], g["end"], g["type"]) ==
                                (loc["start"], loc["end"], candidate["type"])]
                    if expected and any(candidate[k] != expected[0][k] for k in ("negated", "ambiguous")):
                        qualifier_errors.append({"candidate": row,
                            "expected": {k: expected[0][k] for k in ("negated", "ambiguous")},
                            "actual": {k: candidate[k] for k in ("negated", "ambiguous")}})
            for annotation in case["annotations"][kind + "s"]:
                destination = "optional_gold" if annotation.get("optional", False) else "gold"
                pools[kind][destination].append({"source_ref": ref, "source_revision": revision,
                    **{k: annotation[k] for k in ("type", "start", "end", "quote")}})
    return {"split": split, "case_count": len(selected), "annotation_status": "cto_review_amended",
            "case_review_statuses": dict(Counter(c["annotation_status"] for c in selected)),
            "cues": summarize(**pools["cue"]), "mentions": summarize(**pools["mention"]),
            "qualifier_errors": qualifier_errors, "ordinary_use_false_positives": ordinary_false_positives,
            "note": "Lexical cue scores do not establish correct interpretation. No model-quality claim; see per-case CTO review/amendment status."}
