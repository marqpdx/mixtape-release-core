"""Private human review records and text-free aggregate export for shadow.py."""
from collections import Counter, defaultdict
import math
from uuid import uuid4
from typing import Any

from shadow import (KINDS, ROLES, dictionary_matches, digest, frozen, need,
                    now, person, private, read, sha, span, write, matching_module)


def load(workspace, run):
    workspace, run = private(workspace), private(run)
    need(run.parent == workspace, 'run_outside_workspace')
    data, meta = frozen(workspace), read(private(run / 'run.json'))
    need(meta['set_digest'] == data['set_digest'], 'run_set_mismatch')
    need(sha(private(run / 'unaided.json')) == meta['unaided_sha256'], 'unaided_changed')
    evidence = {}
    for note in data['notes']:
        filename = note['note_id'] + '.json'
        need(sha(private(run / filename)) == meta['evidence_sha256'][filename], 'evidence_changed')
        row = read(run / filename)
        need(row['note_id'] == note['note_id'], 'evidence_identity')
        need(row['request']['sources'][0]['text'] == note['text'], 'evidence_source')
        evidence[note['note_id']] = row
    return data, meta, evidence


def validate_reviews(data, meta, evidence, review):
    need(review['run_digest'] == digest(meta), 'review_run_mismatch')
    need(review['wording_digest'] == meta['pinned_context']['review_wording_digest']
         and review['wording'] == meta['pinned_context']['shapes'], 'review_wording_changed')
    notes = {n['note_id']: n for n in data['notes']}
    need(len(review['notes']) == len(notes) and {r['note_id'] for r in review['notes']} == set(notes), 'review_set')
    for row in review['notes']:
        note = notes[row['note_id']]
        need(row['text'] == note['text'] and row['split'] == note['split'], 'review_source_changed')
        need(row['status'] == evidence[note['note_id']]['status'] and
             row['refusal_code'] == evidence[note['note_id']].get('refusal_code'), 'review_status_changed')
        need(row['complete'] is True, 'review_incomplete')
        person(row)
        need(all(type(row[k]) is int and row[k] >= 0 for k in ('seconds', 'actions')), 'review_burden')
        candidates = {c['candidate_id']: c for c in evidence[note['note_id']]['candidates']}
        need(len(row['candidates']) == len(candidates)
             and {c['candidate_id'] for c in row['candidates']} == set(candidates), 'review_candidates')
        for item in row['candidates']:
            original = candidates[item['candidate_id']]
            loc = original['source_locator']
            need(all(item[k] == loc[k] for k in ('quote', 'start', 'end'))
                and item['proposed_type'] == original['type'] and item['score'] == original['score'], 'candidate_changed')
            need(item['span_verdict'] in {'exact', 'wrong_edges', 'not_mention'}, 'span_verdict')
            need(item['role'] in ROLES, 'review_role')
            need(not (item['span_verdict'] == 'not_mention' and item['role'] in KINDS), 'contradictory_review')
            if item['span_verdict'] == 'wrong_edges':
                span(note['text'], item['corrected_span'])
            else:
                need(item['corrected_span'] is None, 'unexpected_corrected_span')
            need(isinstance(item['entity_ref'], str) and bool(item['entity_ref']), 'entity_ref')
        for item in row['missed']:
            span(note['text'], item)
            need(item['role'] in KINDS and isinstance(item['entity_ref'], str)
                 and bool(item['entity_ref']), 'missed_role')


def import_review(workspace, run, reviews):
    data, meta, evidence = load(workspace, run)
    review = read(private(reviews))
    validate_reviews(data, meta, evidence, review)
    destination = private(run) / ('review-' + str(uuid4()) + '.json')
    # Each import is a new immutable snapshot. Earlier/repeat reviewers remain intact.
    write(destination, {'imported_at': now(), 'source_sha256': sha(reviews), 'review': review})
    return {'review_snapshot': str(destination), 'notes': len(review['notes'])}


def interval(success, total):
    if not total:
        return {'value': None, 'n': 0, 'wilson95': None}
    p, z = success / total, 1.959963984540054
    center = (p + z*z/(2*total)) / (1+z*z/total)
    radius = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / (1+z*z/total)
    return {'value': p, 'n': total, 'wilson95': [max(0, center-radius), min(1, center+radius)]}


def match_counts(predicted, gold, overlap=False):
    # Maximum bipartite matching; duplicate predictions count as false positives.
    matches: dict[int, int] = {}
    def visit(index, seen):
        p = predicted[index]
        for j, g in enumerate(gold):
            fits = (p == g) if not overlap else (max(p[0], g[0]) < min(p[1], g[1]))
            if fits and j not in seen:
                seen.add(j)
                if j not in matches or visit(matches[j], seen):
                    matches[j] = index
                    return True
        return False
    tp = sum(visit(i, set()) for i in range(len(predicted)))
    return {'tp': tp, 'fp': len(predicted)-tp, 'fn': len(gold)-tp}


def replay(data, reviews, evidence):
    """Only earlier reviewed notes from the same Folio AND split supply names."""
    stores: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
    result = []
    for note in data['notes']:
        row = reviews[note['note_id']]
        store = stores[(note['folio_id'], note['split'])]
        eligible = len(note['text']) <= 4000
        matches = dictionary_matches(note['text'], list(store.values())) if eligible else []
        predicted = {(c['type'], c['source_locator']['start'], c['source_locator']['end'])
            for c in evidence[note['note_id']]['candidates']}
        lexical = {(m['type'], m['start'], m['end']) for m in matches}
        result.append({'note_id': note['note_id'], 'dictionary_revision': digest(store), 'matches': matches,
            'dictionary_status': 'read' if eligible else 'not_run_source_too_long',
            'both': len(predicted & lexical), 'model_only': len(predicted - lexical),
            'dictionary_only': len(lexical - predicted)})
        confirmations = []
        for item in row['candidates']:
            if item['role'] in KINDS and item['span_verdict'] != 'not_mention':
                confirmations.append({**item, **(item['corrected_span'] or {})})
        confirmations += row['missed']
        gold = {(c['role'], c['start'], c['end']) for c in confirmations}
        result[-1].update(required_gold=len(gold) if eligible else 0,
            dictionary_gold_hits=len(lexical & gold) if eligible else 0,
            model_gold_hits=len(predicted & gold) if eligible else 0,
            union_gold_hits=len((lexical | predicted) & gold) if eligible else 0)
        # Names from this note become available only AFTER all this note's matches.
        old_ids = set(store)
        pending: dict[str, Any] = {}
        for item in confirmations:
            if item['entity_ref'] == 'cant_tell':
                continue
            name = span(note['text'], item)['quote']
            entry_id = item['entity_ref']
            if entry_id == 'new':
                entry_id = f"{note['note_id']}:{item['start']}:{item['end']}:{item['role']}"
            else:
                need(entry_id in old_ids and store[entry_id]['type'] == item['role'], 'entity_reference_not_prior')
            entry = pending.get(entry_id, store.get(entry_id, {'entry_id': entry_id,
                'revision': 0, 'type': item['role'], 'names': []}))
            entry = {**entry, 'names': list(entry['names'])}
            if name not in entry['names']:
                entry['names'].append(name)
                entry['revision'] += 1
            pending[entry_id] = entry
        store.update(pending)
    return result


def tally(workspace, run, reviews):
    data, meta, evidence = load(workspace, run)
    run, reviews = private(run), private(reviews)
    need(reviews.parent == run and reviews.name.startswith('review-'), 'import_review_first')
    review = read(reviews)['review']
    validate_reviews(data, meta, evidence, review)
    indexed = {r['note_id']: r for r in review['notes']}
    dictionary = replay(data, indexed, evidence)
    sections = {}
    for split in ('tuning', 'holdout'):
        selected = [n for n in data['notes'] if n['split'] == split]
        counts: Counter[str] = Counter({k: 0 for k in (
            'notes', 'read', 'refused', 'actions', 'seconds', 'no_candidate', 'candidate_cap_reached',
            'ambiguous_candidates', 'uncertain_candidates', 'overlapping_candidate_pairs',
            'candidates', 'missed_annotations')})
        exact: dict[str, Counter[str]] = {k: Counter() for k in KINDS}
        overlap: dict[str, Counter[str]] = {k: Counter() for k in KINDS}
        scores: dict[str, list[tuple[float, int]]] = {k: [] for k in KINDS}
        for note in selected:
            row, ev = indexed[note['note_id']], evidence[note['note_id']]
            counts['notes'] += 1
            counts[ev['status']] += 1
            counts['actions'] += row['actions']
            counts['seconds'] += row['seconds']
            counts['no_candidate'] += int(ev['status'] == 'read' and not ev['candidates'])
            counts['candidate_cap_reached'] += int(ev.get('candidate_cap_reached', False))
            counts['ambiguous_candidates'] += sum(bool(c['ambiguous']) for c in ev['candidates'])
            counts['uncertain_candidates'] += sum(bool(c['uncertain']) for c in ev['candidates'])
            locators = [c['source_locator'] for c in ev['candidates']]
            counts['overlapping_candidate_pairs'] += sum(
                max(a['start'], b['start']) < min(a['end'], b['end'])
                for i, a in enumerate(locators) for b in locators[i+1:])
            if ev['status'] == 'refused':
                counts['refusal:' + ev['refusal_code']] += 1
            gold = set()
            predicted: dict[str, list[tuple[int, int]]] = {kind: [] for kind in KINDS}
            for item in row['candidates']:
                counts['candidates'] += 1
                counts['role:' + item['role']] += 1
                counts['span:' + item['span_verdict']] += 1
                p = (item['start'], item['end'])
                # Can't-tell is explicitly excluded from precision denominators.
                if item['role'] != 'cant_tell':
                    predicted[item['proposed_type']].append(p)
                    scores[item['proposed_type']].append((item['score'],
                        int(item['role'] == item['proposed_type'] and item['span_verdict'] == 'exact')))
                if item['role'] in KINDS and item['span_verdict'] != 'not_mention':
                    loc = item['corrected_span'] or item
                    gold.add((item['role'], loc['start'], loc['end']))
            for item in row['missed']:
                gold.add((item['role'], item['start'], item['end']))
            counts['missed_annotations'] += len(row['missed'])
            for kind in KINDS:
                target = [(s, e) for k, s, e in gold if k == kind]
                exact[kind].update(match_counts(predicted[kind], target))
                overlap[kind].update(match_counts(predicted[kind], target, True))
        metrics = {}
        for kind in sorted(KINDS):
            bands = []
            for lo in (0.5, 0.6, 0.7, 0.8, 0.9):
                values = [y for s, y in scores[kind] if min(9, int(s*10)) == round(lo*10)]
                bands.append({'lower': lo, 'upper': min(1, lo+0.1), 'confirmed': interval(sum(values), len(values))})
            metrics[kind] = {'exact': dict(exact[kind]), 'overlap': dict(overlap[kind]),
                'precision': interval(exact[kind]['tp'], exact[kind]['tp']+exact[kind]['fp']),
                'recall': interval(exact[kind]['tp'], exact[kind]['tp']+exact[kind]['fn']),
                'brier_candidate_exact': sum((s-y)**2 for s, y in scores[kind])/len(scores[kind]) if scores[kind] else None,
                'score_bands': bands}
        sections[split] = {'counts': dict(counts), 'metrics': metrics,
            'refusal_rate': interval(counts['refused'], len(selected))}
    blind = read(run / 'unaided.json')
    # Comparison uses counts, not text; it is not an independent recall estimate.
    blind_summary = {'notes': len(blind), 'unaided_mentions': sum(len(r['mentions']) for r in blind),
        'assisted_missed_annotations': sum(len(indexed[r['note_id']]['missed']) for r in blind)}
    dictionary_splits = {}
    for split in ('tuning', 'holdout'):
        subset = [r for n, r in zip(data['notes'], dictionary) if n['split'] == split]
        totals = {key: sum(r[key] for r in subset) for key in ('both', 'model_only', 'dictionary_only',
            'required_gold', 'dictionary_gold_hits', 'model_gold_hits', 'union_gold_hits')}
        dictionary_splits[split] = {**totals,
            'dictionary_recall': interval(totals['dictionary_gold_hits'], totals['required_gold']),
            'model_recall': interval(totals['model_gold_hits'], totals['required_gold']),
            'union_recall': interval(totals['union_gold_hits'], totals['required_gold']),
            'not_run_source_too_long': sum(r['dictionary_status'] != 'read' for r in subset)}
    diagnostic_counts: Counter[str] = Counter()
    for item in evidence.values():
        diagnostic = item.get('diagnostic')
        if diagnostic:
            diagnostic_counts[diagnostic['status']] += 1
            for candidate in diagnostic.get('candidates', []):
                diagnostic_counts[candidate['type']] += 1
    report = {'version': '1.0.0', 'created_at': now(), 'set_digest': data['set_digest'],
        'run_digest': digest(meta), 'review_sha256': sha(reviews), 'profile_digest': meta['profile_digest'],
        'manifest_sha256': meta['manifest_sha256'], 'code': meta['code'], 'splits': sections, 'blind_comparison': blind_summary,
        'diagnostic': {'profile_digest': meta['diagnostic_profile_digest'],
            'counts': dict(diagnostic_counts), 'review_metrics': 'not_computed'},
        'dictionary': {**matching_module().identity(),
            'by_split': dictionary_splits},
        'limits': ['one-writer labelled set, not production acceptance',
            'candidate Brier is conditional on emitted, reviewed candidates; not a calibrated confidence claim',
            'cant_tell excluded from precision; counts retained',
            'Dictionary replay isolated by split and based only on earlier confirmed notes',
            'diagnostic outputs not mixed into exact-profile tallies',
            'repeat-review agreement and entity-matching quality require separately adjudicated comparisons']}
    # Private replay has quotes. Public tallies contain only fixed keys/counts/hashes.
    write(run / ('dictionary-replay-' + str(uuid4()) + '.json'), dictionary)
    write(run / ('tallies-' + str(uuid4()) + '.json'), report)
    return report
