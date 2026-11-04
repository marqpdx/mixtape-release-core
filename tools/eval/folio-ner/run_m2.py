"""Run one explicitly selected M2 split, with offline models and pinned artifacts."""
import argparse
import hashlib
import json
import resource
import subprocess
import time
from pathlib import Path

from adapter import digest
from dataset import read_jsonl, write_jsonl
from evaluation import evaluate
from model_adapters import LocalModels, LABELS, SPACY_LABELS, THRESHOLD

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['spacy', 'gliner'], required=True)
    parser.add_argument('--split', choices=['tuning', 'contrast', 'paraphrase', 'holdout'], required=True)
    parser.add_argument('--model-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = ['model_adapters.py', 'run_m2.py', 'm2-requirements.lock']
    subprocess.run(['git', 'ls-files', '--error-unmatch', *paths], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['git', 'diff', '--exit-code', 'HEAD', '--', *paths], cwd=ROOT, check=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    manifest = json.loads((args.model_root / 'download_manifest.json').read_text())
    for path, expected in manifest['sha256'].items():
        if hashlib.sha256((args.model_root / path).read_bytes()).hexdigest() != expected:
            raise ValueError('Model artifact hash mismatch: '+path)
    expected_config = json.loads((args.model_root/'gliner/gliner_config.json').read_text())
    expected_config['model_name'] = str(args.model_root/'encoder')
    if json.loads((args.model_root/'runtime/gliner_config.json').read_text()) != expected_config:
        raise ValueError('Unexpected GLiNER runtime config')
    if (args.model_root/'runtime/pytorch_model.bin').resolve() != (args.model_root/'gliner/pytorch_model.bin').resolve():
        raise ValueError('Unexpected runtime weights')
    args.output.mkdir(parents=True, exist_ok=False)
    cases = list(read_jsonl(ROOT/'cases.jsonl'))
    selected = [case for case in cases if case['split'] == args.split]
    adapter = LocalModels(args.backend, args.model_root)
    responses, raw, times = [], [], []
    for case in selected:
        started = time.perf_counter()
        response, entities = adapter.recognize(case['request'])
        times.append(time.perf_counter()-started)
        responses.append(response)
        raw.append({'case_id': case['id'], 'entities': entities})
    write_jsonl(args.output/'responses.jsonl', responses)
    write_jsonl(args.output/'raw.jsonl', raw)
    summary = evaluate(cases, responses, args.split)
    summary['note'] = 'First local model comparison; generic spaCy mapping and fixed GLiNER labels, not confirmed Fiction interpretation.'
    metadata = {'code_commit': commit, 'code_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        'dataset_sha256': hashlib.sha256((ROOT/'cases.jsonl').read_bytes()).hexdigest(),
        'model_manifest_digest': digest(manifest), 'producer': adapter.producer,
        'label_map': SPACY_LABELS if args.backend == 'spacy' else LABELS,
        'threshold': THRESHOLD if args.backend == 'gliner' else None, 'flat_ner': False,
        'load_seconds': adapter.load_seconds, 'inference_seconds': times,
        'peak_rss_bytes_macos': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'cloud_calls': 0, 'private_cases': 0, 'device': 'cpu', 'torch_threads': 2,
        'bundle_digest': selected[0]['request']['context']['contour']['bundle_digest']}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2))
    (args.output/'metadata.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps({'backend':args.backend,'split':args.split,'mentions':summary['mentions'], 'metadata':metadata},indent=2))


if __name__ == '__main__': main()
