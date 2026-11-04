"""M3 GLiNER baseline: classify a supplied span within its sentence.

Oracle mention locations isolate classification from detection. Traps are none.
This is GLiNER's baseline only, not the planned local-generative/Claude comparison.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from dataset import read_jsonl, write_jsonl
from model_adapters import LocalModels, LABELS

ROOT = Path(__file__).resolve().parent


def sentence(text, start, end):
    boundaries = list(re.finditer(r'[.!?]\s+', text))
    left = max([m.end() for m in boundaries if m.end() <= start] or [0])
    right = min([m.end() for m in boundaries if m.start() >= end] or [len(text)])
    return text[left:right], left


def classify(entities, start, end):
    # Fixed before evaluating: only labels on the same supplied mention,
    # allowing containing spans but never neighbouring names.
    eligible = [e for e in entities if e['start'] <= start < end <= e['end']]
    if not eligible:
        return 'none'
    eligible.sort(key=lambda e: (e['end']-e['start'], -e['score'], e['label']))
    return LABELS[eligible[0]['label']]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-root', type=Path, required=True)
    p.add_argument('--split', choices=['tuning','contrast','paraphrase','holdout'], required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    subprocess.run(['git','ls-files','--error-unmatch','run_m3_gliner.py'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['git','diff','--exit-code','HEAD','--','run_m3_gliner.py','model_adapters.py'],cwd=ROOT,check=True)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    manifest=json.loads((args.model_root/'download_manifest.json').read_text())
    for path, expected_hash in manifest['sha256'].items():
        if hashlib.sha256((args.model_root/path).read_bytes()).hexdigest() != expected_hash:
            raise ValueError('Model artifact hash mismatch')
    expected_config=json.loads((args.model_root/'gliner/gliner_config.json').read_text())
    expected_config['model_name']=str(args.model_root/'encoder')
    if json.loads((args.model_root/'runtime/gliner_config.json').read_text()) != expected_config:
        raise ValueError('Unexpected runtime config')
    if (args.model_root/'runtime/pytorch_model.bin').resolve() != (args.model_root/'gliner/pytorch_model.bin').resolve():
        raise ValueError('Unexpected runtime weights')
    model=LocalModels('gliner',args.model_root)
    results=[]
    started=time.perf_counter()
    for case in read_jsonl(ROOT/'cases.jsonl'):
        if case['split'] != args.split: continue
        text=case['request']['source']['text']
        units=[(a,a['type']) for a in case['annotations']['mentions'] if not a.get('optional',False)]
        units.extend((a,'none') for a in case['annotations']['traps'])
        for annotation,expected in units:
            passage,offset=sentence(text,annotation['start'],annotation['end'])
            entities=model.entities(passage)
            predicted=classify(entities,annotation['start']-offset,annotation['end']-offset)
            results.append({'case_id':case['id'],'source_digest':case['request']['source_digest'],
                'context_digest':case['request']['context_digest'], 'sentence':passage,'sentence_offset':offset,
                'mention':annotation['quote'],'start':annotation['start'],'end':annotation['end'],
                'expected':expected,'predicted':predicted,'correct':expected==predicted,'raw':entities})
    args.output.mkdir(parents=True,exist_ok=False)
    write_jsonl(args.output/'units.jsonl',results)
    summary={'split':args.split,'code_commit':commit,'code_sha256':hashlib.sha256((ROOT/'run_m3_gliner.py').read_bytes()).hexdigest(),
        'unit_count':len(results),'correct':sum(r['correct'] for r in results),
        'confusion':dict(Counter(r['expected']+' -> '+r['predicted'] for r in results)),
        'load_seconds':model.load_seconds,'inference_seconds':time.perf_counter()-started,
        'producer':model.producer,'cloud_calls':0,'note':'Oracle found spans; GLiNER containment baseline; not full M3 or end-to-end quality.'}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
