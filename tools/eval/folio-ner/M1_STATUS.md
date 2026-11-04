# NER Eval M1 — reviewed amendments complete

2026-11-03. M1 implemented on the laptop under the CTO's host override.
Puddlejump accepted the contract as the independent second reader; the original
Mobile-role review was the author's own check. Review handoff:
zz/handoff-2026-11-03-mobile-ner-m1-review.md. Stop before M2.

## Applied A1–A5

21 synthetic cases: 4 tuning, 7 contrast, 5 paraphrase, 5 holdout. Original case
spans and interpretations follow the CTO review; amended and newly authored
cases keep their explicit statuses. New cases: 812-character spoken self-correction
in holdout, 229-character spoken note with no cue words, and possessive/multi-word
names. No private fixture or source text was rewritten.

Leading articles and possessive 's are outside mention spans. baker is optional
gold with a boolean flag: one exact correctly typed hit is neutral in required
metrics and reported separately; duplicates remain errors. negated-scene now
contains a generic train stations trap. Decomposed E + U+0301 in Élodie alongside
precomposed é in Café is intentional; the original mixed code points are tested.
Relaxed overlap is supplemental to exact one-to-one typed span scoring.

## Verification and observed baseline

35 standard-library tests pass (8 original scaffold tests, 27 M1 tests).
`python3 -B run.py compile --check` validates all 21 compiled cases and pinned
Contour context. Original recognition.py/test_recognition.py match frontend
d0ee754e byte-for-byte. Heddle/runtime imports, models and dependencies are absent.

The unchanged cue baseline finds lexical spans 6/6 (tuning), 5/5 (contrast), and
6/6 (paraphrase). Contrast still has two qualifier/ordinary-use errors: manuscript
file location and a quoted scene. It emits no name mentions by design, missing
6 required spans in tuning, 5 in contrast and 10 in paraphrase. The one optional
baker span has zero baseline hits and no false-negative penalty. Holdouts remain
unscored. Exact counts and overlap supplements are in baseline_summary.json.
These are deterministic harness observations, not model-quality evidence.

## Handoff and remaining gates

Report using the NER Eval inbox name, including A1–A5, the deliberate mixed
normalization and new baseline numbers. No M2 without CTO go-ahead and pinned
spaCy/GLiNER/model-package choices and Tier 0 vetting. The private real note waits
for M2 outside git. No server, download, cloud call or registration occurred.
FI-7 resumes alongside this evaluation; its next unit remains models and atomic
services, with migration execution restricted to a test database before CTO review.
