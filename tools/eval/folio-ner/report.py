"""Render case review and cue-only baseline summaries; holdouts stay unscored."""
from collections import Counter
import json
from pathlib import Path

from dataset import read_jsonl
from adapter import recognize
from evaluation import evaluate

ROOT = Path(__file__).resolve().parent


def render():
    cases = list(read_jsonl(ROOT / 'cases.jsonl'))
    counts = Counter(c['split'] for c in cases)
    statuses = Counter(c['annotation_status'] for c in cases)
    context = cases[0]['request']['context']
    review = ['# M1 synthetic case review', '',
        '2026-11-03. CTO/Puddlejump review applied under handoff-2026-11-03-mobile-ner-m1-review.md.',
        'Original cases retain their per-case review/amendment status; the three new cases',
        'are marked authored_to_cto_spec, not falsely labelled individually reviewed.', '',
        '**Mention boundary convention:** leading articles (the/a/an) stay outside the',
        "NER span, and a possessive 's stays outside a name. Shape/passage evidence may",
        'quote broader verbatim text. No source text is rewritten to achieve boundaries.', '',
        '**Optional gold:** baker is descriptive, not a required name mention. A correctly',
        'typed exact optional hit is excluded from TP/FP/FN and reported separately.',
        'Its absence incurs no FN. Duplicate predictions or different types/boundaries',
        'remain ordinary scoring errors. Relaxed overlap is supplementary, never a',
        'replacement for exact scores.', '',
        'Splits: '+', '.join(f'{s} {counts[s]}' for s in ('tuning','contrast','paraphrase','holdout'))+'.',
        'Holdouts remain unscored; one contains the long spoken self-correction.', '',
        '## Pinned context', '', f'Contour bundle: `{context["contour"]["bundle_digest"]}`.',
        'Strategy: writing.fiction_note_reading 0.1.0. Setting cues: setting, locale, location.', '']
    for case in cases:
        review += [f'## {case["id"]} ({case["split"]})', '',
                   f'Review status: `{case["annotation_status"]}`.', '',case['request']['source']['text'], '',
                   f'Source SHA-256: `{case["source_sha256"]}`.', '',case['notes'],'']
        for key,label in [('mentions','Mention gold'),('cues','Lexical cues'),('ambiguities','Ambiguities'),('traps','Traps')]:
            review += [label+':','']
            if not case['annotations'][key]:
                review += ['- none',''];continue
            for a in case['annotations'][key]:
                detail = a.get('type',a.get('reason',''))
                if key == 'cues':detail += f'; negated={a["negated"]}, ambiguous={a["ambiguous"]}'
                if a.get('optional'):detail += '; OPTIONAL (neutral exact hit)'
                if a.get('uncertain'):detail += '; '+'; '.join(a['uncertain'])
                review.append(f'- `{a["quote"]}` [{a["start"]}, {a["end"]}) — {detail}')
            review.append('')
        review += ['Shape judgments (separate from mention scoring):','']
        if not case['annotations']['shape_judgements']:review.append('- none proposed')
        for j in case['annotations']['shape_judgements']:
            quotes='; '.join('`'+a['quote']+'`' for a in j['evidence'])
            review.append(f'- {j["shape_id"]}: {j["judgement"]}; evidence {quotes}')
        review += ['', 'Expected non-actions: '+', '.join(case['non_actions'])+'.','']
    (ROOT/'CASE_REVIEW.md').write_text('\n'.join(review).rstrip()+'\n')
    reports = {}
    for split in ('tuning','contrast','paraphrase'):
        report = evaluate(cases,[recognize(c['request']) for c in cases if c['split']==split],split)
        reports[split] = {'case_count':report['case_count'], 'cues':report['cues']['micro'],
            'mentions':report['mentions']['micro'], 'optional_mentions':report['mentions']['optional'],
            'relaxed_cues':report['cues']['relaxed_overlap_micro'],
            'relaxed_mentions':report['mentions']['relaxed_overlap_micro'],
            'qualifier_error_count':len(report['qualifier_errors']),
            'ordinary_use_false_positive_count':len(report['ordinary_use_false_positives'])}
    (ROOT/'baseline_summary.json').write_text(json.dumps({'baseline':'unchanged deterministic cue scaffold d0ee754e',
        'annotation_status':'cto_review_amended','case_review_statuses':dict(statuses),
        'holdout':'not run','reports':reports},indent=2,sort_keys=True)+'\n')
    provenance=json.loads((ROOT/'PROVENANCE.json').read_text())
    provenance.update(annotation_status='cto_review_amended', case_review_statuses=dict(statuses),
        review_handoff='puddlejump/zz/handoff-2026-11-03-mobile-ner-m1-review.md',
        contract_second_reader='Puddlejump: accepted M1 draft 0.1.0-draft, CTO 2026-11-03')
    (ROOT/'PROVENANCE.json').write_text(json.dumps(provenance,indent=2,sort_keys=True)+'\n')
    print(json.dumps(reports,indent=2,sort_keys=True))


if __name__ == '__main__':
    render()
