"""CTO-run, file-only Selene evaluation. Never imports Django or opens a database."""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from uuid import UUID, uuid4

VERSION = '1.0.0'
HERE = Path(__file__).resolve().parent
KINDS = {'writing.character', 'writing.setting'}
ROLES = KINDS | {'outside_story', 'neither', 'cant_tell'}


class Invalid(ValueError):
    """Only fixed codes may reach the console; never include private values."""


def need(condition, code):
    if not condition:
        raise Invalid(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def private(path):
    """Reject repository/temp aliases and symlinks in every existing ancestor."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        need(not part.is_symlink(), 'symlink_forbidden')
        need(not (part / '.git').exists(), 'private_path_in_repository')
    return path


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write(path, value):
    # Exclusive creation prevents replacement of evidence or human judgements.
    with Path(path).open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def offline():
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
        HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false', DO_NOT_TRACK='1')
    def refuse(*args, **kwargs):
        raise Invalid('network_forbidden')
    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = refuse  # type: ignore[method-assign]
    socket.getaddrinfo = refuse
    socket.create_connection = refuse


def uuid(value):
    need(isinstance(value, str) and str(UUID(value)) == value, 'invalid_uuid')
    return value


def source(row):
    required = {'note_id', 'folio_id', 'capture_order', 'local_only', 'medium',
                'transcript_model', 'transcript_backend', 'text'}
    need(isinstance(row, dict) and set(row) == required, 'input_fields')
    uuid(row['note_id'])
    uuid(row['folio_id'])
    need(type(row['capture_order']) is int and row['capture_order'] >= 0, 'capture_order')
    need(type(row['local_only']) is bool, 'local_only_required')
    need(row['medium'] in {'typed', 'voice'} and isinstance(row['text'], str), 'input_type')
    if row['medium'] == 'typed':
        need(row['transcript_model'] is None and row['transcript_backend'] is None, 'typed_metadata')
    else:
        need(all(isinstance(row[k], str) and row[k] for k in
            ('transcript_model', 'transcript_backend')), 'voice_metadata_required')
    return row


def freeze(input_path, workspace, seed):
    input_path, workspace = private(input_path), private(workspace)
    need(input_path.is_file() and not workspace.exists(), 'new_workspace_required')
    notes = [source(row) for row in rows(input_path)]
    need(bool(notes), 'empty_set')
    need(len({n['note_id'] for n in notes}) == len(notes), 'duplicate_note')
    need(len({(n['folio_id'], n['capture_order']) for n in notes}) == len(notes), 'duplicate_capture_order')
    # Same text cannot straddle tuning/holdout, even under different note IDs.
    for note in notes:
        text_hash = hashlib.sha256(note['text'].encode()).hexdigest()
        partition = int(digest({'seed': seed, 'text_sha256': text_hash})[:8], 16)
        note.update(source_sha256=text_hash, split='holdout' if partition % 5 == 0 else 'tuning',
                    blind=bool((partition // 5) % 5 == 0))
    notes.sort(key=lambda n: (n['folio_id'], n['capture_order']))
    frozen = {'version': VERSION, 'created_at': now(), 'seed': seed, 'notes': notes}
    frozen['set_digest'] = digest(notes)
    workspace.mkdir(parents=True, mode=0o700, exist_ok=False)
    write(workspace / 'frozen.json', frozen)
    blind = [{'note_id': n['note_id'], 'text': n['text'], 'complete': False,
              'actor': '', 'reviewed_at': '', 'mentions': []} for n in notes if n['blind']]
    write(workspace / 'unaided-template.json', blind)
    return {'notes': len(notes), 'blind_notes': len(blind), 'set_digest': frozen['set_digest']}


def frozen(workspace):
    data = read(private(private(workspace) / 'frozen.json'))
    need(data['version'] == VERSION and digest(data['notes']) == data['set_digest'], 'frozen_set_changed')
    return data


def span(text, item):
    need(isinstance(item, dict), 'span_object')
    start, end = item.get('start'), item.get('end')
    need(type(start) is int and type(end) is int and 0 <= start < end <= len(text), 'invalid_span')
    return {'start': start, 'end': end, 'quote': text[start:end]}


def person(row):
    need(isinstance(row.get('actor'), str) and bool(row['actor'].strip()), 'review_actor_required')
    stamp = datetime.fromisoformat(row['reviewed_at'])
    need(stamp.tzinfo is not None, 'review_timezone_required')


def unaided_check(data, annotations):
    blind = {n['note_id']: n for n in data['notes'] if n['blind']}
    need(len(annotations) == len(blind), 'unaided_incomplete')
    need({r['note_id'] for r in annotations} == set(blind), 'unaided_identity')
    for row in annotations:
        person(row)
        need(row['text'] == blind[row['note_id']]['text'], 'unaided_source_changed')
        need(row.get('complete') is True, 'unaided_incomplete')
        for item in row['mentions']:
            span(blind[row['note_id']]['text'], item)
            need(item['role'] in KINDS, 'unaided_role')


def context(bundle_path):
    import yaml
    bundle = read(bundle_path)
    need(bundle['digest'] == digest({k: v for k, v in bundle.items() if k != 'digest'}), 'bundle_digest')
    need(all(hashlib.sha256(e['text'].encode()).hexdigest() == e['sha256']
        for e in bundle['files'].values()), 'bundle_file_digest')
    files = {p: e for p, e in bundle['files'].items() if p.startswith(('writing/', 'shared/'))}
    strategy = yaml.safe_load(files['writing/strategies/fiction-note-recognition.strategy.yaml']['text'])
    need((strategy['id'], strategy['version']) == ('writing.fiction_note_recognition', '0.1.0'), 'strategy_version')
    shapes = {}
    for label in ('character', 'setting'):
        item = yaml.safe_load(files[f'writing/{label}.shape.yaml']['text'])
        need(item['version'] == '0.2.0', 'shape_version')
        shapes['writing.' + label] = {k: item[k] for k in ('version', 'description', 'disambiguation', 'synonyms')}
    return {'bundle': {'digest': bundle['digest'], 'library_version': bundle['library_version'],
        'source_commit': bundle['source_commit']}, 'dependency_digest': digest(files), 'shapes': shapes,
        'review_wording_digest': digest(shapes), 'strategy': strategy}


def request(note, pinned, wire):
    sources = [{'source_ref': 'offline_note:' + note['note_id'], 'source_revision': 0, 'text': note['text']}]
    ctx = {'revision': 0, 'folio_id': note['folio_id'], 'work_type': 'fiction', 'bundle': pinned['bundle'],
           'dependency_digest': pinned['dependency_digest']}
    # UUIDs are wire identities only: no database record or authorized Heddle run is claimed.
    binding = {'weave_action_run_id': str(uuid4()), 'execution_action_run_id': str(uuid4()),
        'attempt_id': str(uuid4()), 'revision': 0, 'source_digest': wire.digest(sources),
        'context_revision': 0, 'context_digest': wire.digest(ctx), 'contract_version': '0.1.0',
        'prompt_version': '0.1.0', 'strategy_id': 'writing.fiction_note_recognition', 'strategy_version': '0.1.0',
        'steps_digest': digest(pinned['strategy']), 'bundle_digest': pinned['bundle']['digest'],
        'reference_fields_digest': digest({}), 'step_id': 'mention_recognition', 'step_version': '0.1.0',
        'input_digest': digest({'sources': sources, 'context': ctx})}
    return {'protocol': wire.PROTOCOL, 'profile_digest': wire.PROFILE_DIGEST, 'binding': binding,
            'sources': sources, 'context': ctx, 'local_only': True}


def cue_spans(text, pinned):
    result = []
    for kind, shape in pinned['shapes'].items():
        for term in shape['synonyms']:
            for match in re.finditer(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text, re.I):
                prefix = text[max(0, match.start() - 32):match.start()]
                result.append({'type': kind, **span(text, {'start': match.start(), 'end': match.end()}),
                    'negated': bool(re.search(r"\b(?:not|isn't|isn’t|no)(?:\s+(?:a|an|the))?\s*$", prefix, re.I)),
                    'ambiguous': True})
    return result


def matching_module():
    # Folio's committed matcher is pure stdlib. Do not import models or Django.
    sys.path.insert(0, str(HERE.parents[2] / 'app'))
    return importlib.import_module('folio.dictionary.matching')


def normalized(text):
    return matching_module().match_key(text)


def dictionary_matches(text, entries):
    """Adapt private eval entries to Folio's one shared Unicode matcher."""
    need(len(text) <= 4000, 'dictionary_source_budget')
    if not entries:
        return []
    values = []
    types = {}
    for entry in entries:
        need(isinstance(entry['names'], list) and bool(entry['names']) and
             all(isinstance(n, str) and bool(n) for n in entry['names']), 'empty_dictionary_name')
        values.append({'entry_id': entry['entry_id'], 'revision': entry['revision'],
            'names': {'main': entry['names'][0], 'variants': entry['names'][1:]}})
        types[(entry['entry_id'], entry['revision'])] = entry['type']
    result = []
    for hit in matching_module().find_matches(text, values):
        for alternative in hit['alternatives']:
            result.append({**alternative, 'type': types[(alternative['entry_id'], alternative['entry_revision'])],
                'start': hit['start'], 'end': hit['end'], 'quote': hit['quote'],
                'word_bounded': hit['word_bounded'], 'rule': hit['rule']})
    return result


def code_identity(selene_root):
    result = {}
    for root, paths in ((HERE.parents[2], ['tools/eval/folio-ner/shadow.py', 'tools/eval/folio-ner/shadow_report.py',
                         'app/folio/dictionary/matching.py']),
                        (selene_root, ['selene/gliner_adapter.py', 'selene/recognition_contract.py',
                         'selene/artifacts.py', 'selene/contracts/profile.json',
                         'selene/contracts/request.schema.json', 'selene/contracts/response.schema.json',
                         'selene/contracts/model-config.json'])):
        subprocess.run(['git', 'ls-files', '--error-unmatch', '--', *paths], cwd=root,
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *paths], cwd=root, check=True)
        result[str(root.name)] = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
            cwd=root, text=True).strip(), 'subject': subprocess.check_output(['git', 'log', '-1', '--format=%s'],
            cwd=root, text=True).strip(), 'files': {p: sha(root / p) for p in paths}}
    return result


@contextlib.contextmanager
def quiet_model_output():
    """Suppress Python streams and native writes to stdout/stderr during inference."""
    with open(os.devnull, 'w') as sink:
        sys.stdout.flush()
        sys.stderr.flush()
        saved = [os.dup(fd) for fd in (1, 2)]
        try:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                yield
        finally:
            for fd, original in zip((1, 2), saved):
                os.dup2(original, fd)
                os.close(original)


def environment(selene_root):
    profile = read(selene_root / 'selene/contracts/profile.json')
    expected = {'gliner': profile['library_version'], 'torch': profile['torch_version'],
                'transformers': profile['transformers_version'],
                'protobuf': '5.29.5'}  # DeBERTa fast-tokenizer conversion; SE-P/M2 pin.
    versions: dict[str, str | None] = {}
    failures = []
    for name in (*expected, 'PyYAML', 'jsonschema', 'pydantic'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
        if versions[name] is None or (name in expected and versions[name] != expected[name]):
            failures.append(name)
    return {'ready': not failures, 'versions': versions, 'missing_or_conflicting': failures,
            'model_loaded': False, 'input_read': False}


def run(workspace, package, selene_root, bundle, unaided_path, diagnostic_threshold=None):
    import time
    import resource
    need(environment(selene_root)['ready'], 'runtime_environment_unavailable_run_preflight')
    workspace, package = private(workspace), private(package)
    data = frozen(workspace)
    unaided = read(private(unaided_path)) if unaided_path else []
    unaided_check(data, unaided)
    if diagnostic_threshold is not None:
        need(math.isfinite(diagnostic_threshold) and 0 < diagnostic_threshold < 0.5, 'diagnostic_threshold')
    identity = code_identity(selene_root)
    offline()
    sys.path.insert(0, str(selene_root))
    from selene import recognition_contract as wire
    from selene.artifacts import verify_manifest
    from selene.gliner_adapter import load_gliner, package_config, PINNED_FILES
    specs = verify_manifest(package / 'artifacts', package / 'manifest.json')
    need(len(specs) == 1 and specs[0].name == 'gliner-small-v2.1', 'single_gliner_package_required')
    spec = specs[0]
    model_dir = package / 'artifacts' / spec.directory
    package_config(model_dir)
    hashes = {f.path: f.sha256 for f in spec.files}
    need(all(hashes.get(p) == h for p, h in PINNED_FILES.items()), 'pinned_artifacts')
    pinned = context(bundle)
    output = workspace / ('run-' + str(uuid4()))
    output.mkdir(mode=0o700)
    write(output / 'unaided.json', unaided)
    adapter, load_seconds = None, None
    evidence = []
    for note in data['notes']:
        req = request(note, pinned, wire)
        row = {'note_id': note['note_id'], 'semantic_interpretation': 'not_run',
               'status': 'refused', 'candidates': [], 'request': req, 'cues': cue_spans(note['text'], pinned)}
        try:
            wire.validate_request(req)
            if adapter is None:
                started = time.perf_counter()
                adapter = load_gliner(model_dir, spec)
                load_seconds = time.perf_counter() - started
            row['preflight'] = adapter.preflight([note['text']])
            start = time.perf_counter()
            response = adapter.recognize(req)
            row['inference_seconds'] = time.perf_counter() - start
            wire.validate_response(req, response)
            row.update(status='read', response=response, candidates=response['candidates'],
                       candidate_cap_reached=len(response['candidates']) == wire.PROFILE['max_candidates'])
            if diagnostic_threshold is not None:
                # Separate diagnostic profile/record; never mutate production globals.
                raw = adapter.model.batch_predict_entities([note['text']], list(wire.PROFILE['labels']),
                    threshold=diagnostic_threshold, flat_ner=False, multi_label=False)
                need(isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], list), 'diagnostic_output')
                checked = []
                for item in raw[0]:
                    loc = span(note['text'], item)
                    need(item['text'] == loc['quote'] and item['label'] in wire.PROFILE['labels'], 'diagnostic_span')
                    need(type(item['score']) in (int, float) and math.isfinite(item['score'])
                        and 0 <= item['score'] <= 1, 'diagnostic_score')
                    checked.append({**loc, 'type': 'writing.' + item['label'], 'score': item['score']})
                row['diagnostic'] = ({'status': 'read', 'candidates': checked}
                    if len(checked) <= wire.PROFILE['max_candidates'] else
                    {'status': 'refused', 'refusal_code': 'candidate_budget', 'raw_candidates': checked})
        except wire.RecognitionError as exc:
            row.update(status='refused', refusal_code=exc.code)
        # Save completed notes independently so a later native failure loses no earlier evidence.
        write(output / (note['note_id'] + '.json'), row)
        evidence.append(row)
    diagnostic = None if diagnostic_threshold is None else {**wire.PROFILE,
        'id': 'offline-diagnostic-lower-threshold/1', 'threshold': diagnostic_threshold}
    meta = {'version': VERSION, 'run_id': output.name, 'created_at': now(), 'set_digest': data['set_digest'],
        'profile': wire.PROFILE, 'profile_digest': wire.PROFILE_DIGEST, 'pinned_context': pinned,
        'manifest_sha256': sha(package / 'manifest.json'), 'code': identity,
        'diagnostic_profile': diagnostic, 'diagnostic_profile_digest': digest(diagnostic) if diagnostic else None,
        'load_seconds': load_seconds, 'peak_rss_bytes_macos': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'platform': sys.platform, 'machine': os.uname().machine,
        'runtime_versions': {name: importlib.metadata.version(name) for name in ('gliner', 'torch', 'transformers')},
        'evidence_sha256': {n['note_id'] + '.json': sha(output / (n['note_id'] + '.json')) for n in data['notes']},
        'unaided_sha256': sha(output / 'unaided.json'), 'accounting': 'offline UUIDs only; no ActionRuns created',
        'dictionary_matching': matching_module().identity(),
        'dictionary': 'evaluation-only replay from human decisions using shared Folio matcher; no production writes'}
    write(output / 'run.json', meta)
    sheets = []
    for note, row in zip(data['notes'], evidence):
        sheets.append({'note_id': note['note_id'], 'text': note['text'], 'split': note['split'],
            'status': row['status'], 'refusal_code': row.get('refusal_code'), 'actor': '', 'reviewed_at': '',
            'complete': False, 'seconds': 0, 'actions': 0, 'candidates': [
                {'candidate_id': c['candidate_id'], 'quote': c['source_locator']['quote'],
                 'start': c['source_locator']['start'], 'end': c['source_locator']['end'], 'score': c['score'],
                 'proposed_type': c['type'], 'span_verdict': '', 'role': '', 'corrected_span': None,
                 'entity_ref': 'new'} for c in row['candidates']], 'missed': []})
    write(output / 'review-template.json', {'run_digest': digest(meta),
        'wording': pinned['shapes'], 'wording_digest': pinned['review_wording_digest'], 'notes': sheets})
    return {'run_directory': str(output), 'notes': len(evidence),
            'read': sum(r['status'] == 'read' for r in evidence), 'refused': sum(r['status'] == 'refused' for r in evidence)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    env_cmd = commands.add_parser('preflight')
    env_cmd.add_argument('--selene-root', type=Path, required=True)
    freeze_cmd = commands.add_parser('freeze')
    freeze_cmd.add_argument('--input', type=Path, required=True)
    freeze_cmd.add_argument('--workspace', type=Path, required=True)
    freeze_cmd.add_argument('--seed', required=True)
    run_cmd = commands.add_parser('run')
    run_cmd.add_argument('--workspace', type=Path, required=True)
    run_cmd.add_argument('--model-package', type=Path, required=True)
    run_cmd.add_argument('--selene-root', type=Path, required=True)
    run_cmd.add_argument('--bundle', type=Path, default=HERE.parents[2] / 'app/heddle/contour_bundle.json')
    run_cmd.add_argument('--unaided-review', type=Path)
    run_cmd.add_argument('--diagnostic-threshold', type=float)
    for name in ('review', 'tally'):
        cmd = commands.add_parser(name)
        cmd.add_argument('--workspace', type=Path, required=True)
        cmd.add_argument('--run', type=Path, required=True)
        cmd.add_argument('--reviews', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'preflight':
        result = environment(args.selene_root.resolve())
    elif args.command == 'freeze':
        result = freeze(args.input, args.workspace, args.seed)
    elif args.command == 'run':
        # Suppress library console output: only the fixed aggregate result goes to stdout.
        # This does not replace the CTO disabling networking at the OS level.
        with quiet_model_output():
            result = run(args.workspace, args.model_package, args.selene_root.resolve(), args.bundle,
                         args.unaided_review, args.diagnostic_threshold)
    else:
        from shadow_report import import_review, tally
        result = (import_review if args.command == 'review' else tally)(args.workspace, args.run, args.reviews)
    print(json.dumps(result, allow_nan=False))
    if args.command == 'preflight' and not result['ready']:
        sys.exit(2)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Model libraries may embed source text in exceptions. Never echo it/traceback.
        print('Shadow runner failed: ' + (str(exc) if isinstance(exc, Invalid) else 'operation_failed'), file=sys.stderr)
        sys.exit(1)
