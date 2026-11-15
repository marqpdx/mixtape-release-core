"""Synthetic boundary/lifecycle tests; no real notes, model load or database."""
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import shadow as s
import shadow_report as report

# Staged tests can override paths; installed tests default to sibling checkouts.
RELEASE = Path(__file__).resolve().parents[4] if Path(__file__).resolve().parents[1].name == 'eval' else Path('~/Sites/ml/active/mixtape/release')
SELENE = Path(os.environ.get('SELENE_TEST_ROOT', RELEASE / 'mixtape-release-selene'))
CORE = Path(os.environ.get('CORE_TEST_ROOT', RELEASE / 'mixtape-release-core'))
sys.path.insert(0, str(SELENE))
from selene import recognition_contract as wire


def note(text='Nell arrives.', folio=None, order=0):
    return {'note_id': str(uuid4()), 'folio_id': folio or str(uuid4()), 'capture_order': order,
            'local_only': True, 'medium': 'typed', 'transcript_model': None,
            'transcript_backend': None, 'text': text}


class FakeAdapter:
    @property
    def model(self):
        return self

    def batch_predict_entities(self, texts, labels, **kwargs):
        return [[{'start': 0, 'end': 4, 'text': texts[0][:4], 'label': 'character', 'score': 0.3}]]

    def preflight(self, texts):
        if len(texts[0].split()) > 384:
            raise wire.RecognitionError('source_word_budget', 413)
        return [{'words': len(texts[0].split()), 'encoder_tokens': 8}]

    def recognize(self, req):
        candidates = []
        src = req['sources'][0]
        if 'Nell' in src['text']:
            start = src['text'].index('Nell')
            loc = {'source_ref': src['source_ref'], 'source_revision': 0,
                   'start': start, 'end': start+4, 'quote': 'Nell'}
            kind = 'writing.character'
            cid = 'm-' + wire.digest({'execution_action_run_id': req['binding']['execution_action_run_id'],
                                      'type': kind, 'source_locator': loc})[:32]
            candidates.append({'candidate_id': cid, 'candidate_kind': 'mention', 'type': kind,
                'source_locator': loc, 'score': 0.8, 'negated': False, 'ambiguous': True,
                'uncertain': ['Provisional'], 'producer': dict(wire.PRODUCER)})
        return {'protocol': wire.PROTOCOL, 'profile_digest': wire.PROFILE_DIGEST,
            'binding': req['binding'], 'request_fingerprint': wire.digest(req), 'candidates': candidates}


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.input = self.root / 'notes.jsonl'
        self.workspace = self.root / 'private'

    def tearDown(self):
        self.tmp.cleanup()

    def freeze(self, notes):
        self.input.write_text(''.join(json.dumps(n) + '\n' for n in notes))
        s.freeze(self.input, self.workspace, 'synthetic-seed')
        return s.frozen(self.workspace)

    def test_reject_repository_output(self):
        (self.root / '.git').write_text('gitdir: elsewhere')
        with self.assertRaises(s.Invalid):
            s.private(self.root / 'nested' / 'private')

    def test_reject_symlink_ancestor(self):
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(s.Invalid):
            s.private(self.root / 'alias' / 'private')

    def test_exclusive_evidence_write(self):
        s.write(self.root / 'record.json', {'x': 1})
        with self.assertRaises(FileExistsError):
            s.write(self.root / 'record.json', {'x': 2})
        self.assertEqual((self.root / 'record.json').stat().st_mode & 0o777, 0o600)

    def test_freeze_preserves_unicode_and_long_notes(self):
        n = note('🦉 Cafe\u0301 ' + 'x'*4100)
        data = self.freeze([n])
        self.assertEqual(data['notes'][0]['text'], n['text'])
        self.assertTrue(data['notes'][0]['local_only'])

    def test_duplicate_text_same_split(self):
        data = self.freeze([note(), note(order=1)])
        self.assertEqual(data['notes'][0]['split'], data['notes'][1]['split'])

    def test_frozen_mutation_rejected(self):
        self.freeze([note()])
        data = s.read(self.workspace / 'frozen.json')
        data['notes'][0]['text'] = 'Changed'
        (self.workspace / 'frozen.json').write_text(json.dumps(data))
        with self.assertRaises(s.Invalid):
            s.frozen(self.workspace)

    def test_duplicate_note_rejected(self):
        n = note()
        with self.assertRaises(s.Invalid):
            self.freeze([n, n])

    def test_voice_requires_backend(self):
        n = note()
        n['medium'] = 'voice'
        with self.assertRaises(s.Invalid):
            s.source(n)

    def test_local_only_requires_bool(self):
        n = note()
        n['local_only'] = 1
        with self.assertRaises(s.Invalid):
            s.source(n)

    def test_unaided_review_required(self):
        data = {'notes': [{**note(), 'blind': True}]}
        with self.assertRaises(s.Invalid):
            s.unaided_check(data, [])

    def test_dictionary_canonical_and_case_expansion(self):
        entries = [{'entry_id': 'e', 'revision': 1, 'type': 'writing.setting',
                    'names': ['STRASSE', 'Straße', 'Café']}]
        hits = s.dictionary_matches('🦉 Straße Cafe\u0301', entries)
        self.assertEqual([(h['start'], h['end'], h['quote']) for h in hits],
                         [(2, 8, 'Straße'), (9, 14, 'Cafe\u0301')])
        self.assertEqual(s.dictionary_matches('ß', [{**entries[0], 'names': ['s']}]), [])
        self.assertEqual(s.dictionary_matches('e\u0301', [{**entries[0], 'names': ['e']}]), [])

    def test_dictionary_preserves_alternatives_not_accents(self):
        entries = [{'entry_id': k, 'revision': 1, 'type': 'writing.character', 'names': ['Nell']}
                   for k in ('one', 'two')]
        self.assertEqual(len(s.dictionary_matches('Nell', entries)), 2)
        self.assertNotEqual(s.normalized('Cafe'), s.normalized('Café'))

    def test_hangul_normalization_boundary(self):
        entry = {'entry_id': 'e', 'revision': 1, 'type': 'writing.setting', 'names': ['가']}
        hit, = s.dictionary_matches('\u1100\u1161', [entry])
        self.assertEqual((hit['start'], hit['end']), (0, 2))

    def test_empty_name_refused(self):
        with self.assertRaises(s.Invalid):
            s.dictionary_matches('x', [{'names': ['']}])

    def test_overlap_matching_does_not_double_count(self):
        self.assertEqual(report.match_counts([(0, 4), (0, 4)], [(0, 4)]), {'tp': 1, 'fp': 1, 'fn': 0})
        self.assertEqual(report.match_counts([(0, 4), (2, 6)], [(1, 5)], True)['tp'], 1)

    def test_intervals_empty(self):
        self.assertIsNone(report.interval(0, 0)['value'])
        self.assertLess(report.interval(10, 10)['wilson95'][0], 1)

    def exercise(self, diagnostic_threshold=None):
        data = self.freeze([note('Nell arrives.'), note('word '*385), note('x'*4001)])
        annotations = [{'note_id': n['note_id'], 'text': n['text'], 'actor': 'synthetic-reviewer',
            'reviewed_at': s.now(), 'complete': True, 'mentions': []} for n in data['notes'] if n['blind']]
        unaided = self.root / 'unaided.json'
        unaided.write_text(json.dumps(annotations))
        package = self.root / 'package'
        package.mkdir()
        (package / 'manifest.json').write_text('{}')
        spec = SimpleNamespace(name='gliner-small-v2.1', directory='gliner', files=[])
        with patch.object(s, 'code_identity', return_value={'synthetic': True}), \
             patch.object(s, 'environment', return_value={'ready': True}):
            with patch('selene.artifacts.verify_manifest', return_value=(spec,)), \
                 patch('selene.gliner_adapter.package_config'), \
                 patch('selene.gliner_adapter.PINNED_FILES', {}), \
                 patch('selene.gliner_adapter.load_gliner', return_value=FakeAdapter()), \
                 patch.object(s.importlib.metadata, 'version', return_value='synthetic'):
                result = s.run(self.workspace, package, SELENE,
                    CORE / 'app/heddle/contour_bundle.json', unaided, diagnostic_threshold)
        run = Path(result['run_directory'])
        sheet = s.read(run / 'review-template.json')
        for row in sheet['notes']:
            row.update(actor='synthetic-reviewer', reviewed_at=s.now(), complete=True)
            for c in row['candidates']:
                c.update(span_verdict='exact', role='writing.character')
        reviews = self.root / 'filled-review.json'
        reviews.write_text(json.dumps(sheet))
        return data, run, sheet, reviews

    def test_synthetic_lifecycle_refusals_and_text_free_tallies(self):
        data, run, sheet, reviews = self.exercise()
        imported = report.import_review(self.workspace, run, reviews)
        result = report.tally(self.workspace, run, Path(imported['review_snapshot']))
        serialized = json.dumps(result)
        self.assertNotIn('Nell', serialized)
        self.assertNotIn('synthetic-reviewer', serialized)
        self.assertNotIn('note_id', serialized)
        counts = Counter()
        for section in result['splits'].values():
            counts.update(section['counts'])
        self.assertEqual(counts['read'], 1)
        self.assertEqual(counts['refused'], 2)
        self.assertEqual(counts['refusal:source_too_long'], 1)
        self.assertEqual(counts['refusal:source_word_budget'], 1)
        second = report.import_review(self.workspace, run, reviews)
        self.assertNotEqual(second['review_snapshot'], imported['review_snapshot'])

    def test_review_identity_and_evidence_tamper(self):
        _, run, sheet, reviews = self.exercise()
        sheet['run_digest'] = 'wrong'
        reviews.write_text(json.dumps(sheet))
        with self.assertRaises(s.Invalid):
            report.import_review(self.workspace, run, reviews)
        evidence = next(run.glob('????????-????-????-????-????????????.json'))
        evidence.write_text('{}')
        with self.assertRaises(s.Invalid):
            report.load(self.workspace, run)

    def test_review_cannot_rewrite_candidate(self):
        _, run, sheet, reviews = self.exercise()
        row = next(r for r in sheet['notes'] if r['candidates'])
        row['candidates'][0]['quote'] = 'Wrong'
        reviews.write_text(json.dumps(sheet))
        with self.assertRaises(s.Invalid):
            report.import_review(self.workspace, run, reviews)

    def test_diagnostic_profile_separate_and_production_unchanged(self):
        accepted_digest = wire.PROFILE_DIGEST
        _, run, _, reviews = self.exercise(0.25)
        meta = s.read(run / 'run.json')
        self.assertEqual(meta['profile']['threshold'], 0.5)
        self.assertEqual(meta['diagnostic_profile']['threshold'], 0.25)
        self.assertNotEqual(meta['diagnostic_profile_digest'], accepted_digest)
        self.assertEqual(wire.PROFILE_DIGEST, accepted_digest)
        imported = report.import_review(self.workspace, run, reviews)
        result = report.tally(self.workspace, run, Path(imported['review_snapshot']))
        self.assertEqual(result['diagnostic']['counts']['writing.character'], 1)
        self.assertEqual(sum(v['counts']['candidates'] for v in result['splits'].values()), 1)

    def test_wrong_edges_and_outside_story_are_not_exact_hits(self):
        _, run, sheet, reviews = self.exercise()
        row = next(r for r in sheet['notes'] if r['candidates'])
        candidate = row['candidates'][0]
        candidate.update(span_verdict='wrong_edges', corrected_span={'start': 0, 'end': 5})
        reviews.write_text(json.dumps(sheet))
        imported = report.import_review(self.workspace, run, reviews)
        metrics = report.tally(self.workspace, run, Path(imported['review_snapshot']))['splits'][row['split']]['metrics']['writing.character']
        self.assertEqual(metrics['exact'], {'tp': 0, 'fp': 1, 'fn': 1})
        self.assertEqual(metrics['overlap'], {'tp': 1, 'fp': 0, 'fn': 0})
        candidate.update(span_verdict='exact', corrected_span=None, role='outside_story')
        reviews.write_text(json.dumps(sheet))
        imported = report.import_review(self.workspace, run, reviews)
        metrics = report.tally(self.workspace, run, Path(imported['review_snapshot']))['splits'][row['split']]['metrics']['writing.character']
        self.assertEqual(metrics['exact'], {'tp': 0, 'fp': 1, 'fn': 0})

    def test_missing_runtime_fails_before_private_input(self):
        with patch.object(s, 'environment', return_value={'ready': False}), \
             patch.object(s, 'frozen', side_effect=AssertionError('private input read')):
            with self.assertRaisesRegex(s.Invalid, 'runtime_environment_unavailable'):
                s.run(self.workspace, self.root, SELENE, self.root, None)

    def test_runtime_metadata_check_imports_no_native_library(self):
        with patch.object(s.importlib.metadata, 'version', side_effect=s.importlib.metadata.PackageNotFoundError):
            result = s.environment(SELENE)
        self.assertFalse(result['ready'])
        self.assertIn('gliner', result['missing_or_conflicting'])
        self.assertNotIn('torch', sys.modules)

    def test_unaided_source_cannot_change(self):
        n = {**note(), 'blind': True}
        row = {'note_id': n['note_id'], 'text': 'changed', 'actor': 'synthetic',
               'reviewed_at': s.now(), 'complete': True, 'mentions': []}
        with self.assertRaisesRegex(s.Invalid, 'unaided_source_changed'):
            s.unaided_check({'notes': [n]}, [row])

    def test_frozen_file_symlink_rejected(self):
        self.workspace.mkdir()
        (self.workspace / 'frozen.json').symlink_to(self.root / 'outside.json')
        with self.assertRaises(s.Invalid):
            s.frozen(self.workspace)

    def test_console_exception_does_not_echo_private_input(self):
        self.input.write_text('PRIVATE_SENTINEL broken json')
        result = subprocess.run([sys.executable, '-B', str(Path(s.__file__)), 'freeze',
            '--input', str(self.input), '--workspace', str(self.workspace), '--seed', 'synthetic'],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('PRIVATE_SENTINEL', result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_native_and_python_console_output_suppressed(self):
        script = "import os, shadow;\nwith shadow.quiet_model_output():\n print('PRIVATE_SENTINEL'); os.write(2, b'PRIVATE_NATIVE')\nprint('aggregate')"
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=Path(s.__file__).parent,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'aggregate\n')
        self.assertEqual(result.stderr, '')

    def test_dictionary_replay_no_self_or_cross_split(self):
        folio = str(uuid4())
        ns = [{**note('Nell', folio, i), 'split': split} for i, split in enumerate(('tuning', 'holdout', 'tuning'))]
        rs = {n['note_id']: {'candidates': [], 'missed': [
            {'start': 0, 'end': 4, 'role': 'writing.character', 'entity_ref': 'new'}]} for n in ns}
        ev = {n['note_id']: {'candidates': []} for n in ns}
        result = report.replay({'notes': ns}, rs, ev)
        self.assertEqual([len(r['matches']) for r in result], [0, 0, 1])


from collections import Counter
if __name__ == '__main__':
    unittest.main()
