"""Offline M1 commands. All paths local; standard library only."""
import argparse
import json
from pathlib import Path
import sys

from adapter import load_context, recognize
from dataset import compile_cases, read_jsonl, write_jsonl
from evaluation import evaluate

ROOT = Path(__file__).resolve().parent
DEFAULT_BUNDLE = ROOT.parents[2] / "app/heddle/contour_bundle.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["compile", "requests", "adapter", "evaluate", "baseline"])
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--cases", type=Path, default=ROOT / "cases.jsonl")
    parser.add_argument("--split", choices=["tuning", "contrast", "paraphrase", "holdout"])
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.command == "compile":
        rows = json.loads((ROOT / "cases.source.json").read_text())
        cases = compile_cases(rows, load_context(args.bundle))
        if args.check:
            if list(read_jsonl(args.cases)) != cases:
                raise ValueError("Compiled dataset drift: inspect before regenerating")
            print(f"Validated {len(cases)} case annotations and pinned Contour context")
        else:
            write_jsonl(args.cases, cases)
            print(f"Compiled {len(cases)} case annotations into {args.cases}")
        return
    if args.command == "adapter":
        for line in sys.stdin:
            if line.strip():
                print(json.dumps(recognize(json.loads(line)), ensure_ascii=False, sort_keys=True))
        return
    if not args.split:
        parser.error("Choose a split explicitly; never pool tuning and holdout by default")
    cases = list(read_jsonl(args.cases))
    if args.command == "requests":
        for case in cases:
            if case["split"] == args.split:
                print(json.dumps(case["request"], ensure_ascii=False, sort_keys=True))
        return
    if args.command == "baseline":
        responses = [recognize(case["request"]) for case in cases if case["split"] == args.split]
    else:
        if not args.responses:
            parser.error("--responses is required for evaluate")
        responses = list(read_jsonl(args.responses))
    print(json.dumps(evaluate(cases, responses, args.split), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"M1 validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
