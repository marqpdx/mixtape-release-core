"""Explicitly synthetic, file-only native smoke. Launch under macOS deny-network sandbox."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import errno
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from uuid import NAMESPACE_URL, uuid5


def stamp():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sample(pid=None):
    result={'at_utc':stamp(), 'monotonic':time.monotonic()}
    for key, command in (('swap',['/usr/sbin/sysctl','vm.swapusage']),('vm_stat',['/usr/bin/vm_stat'])):
        p=subprocess.run(command,capture_output=True,text=True)
        result[key]=p.stdout.strip() if p.returncode==0 else 'unavailable'
    if pid:
        try:
            p=subprocess.run(['/bin/ps','-o','rss=','-p',str(pid)],capture_output=True,text=True)
            result['process_rss_kib']=int(p.stdout.strip()) if p.returncode==0 and p.stdout.strip() else None
        except OSError:
            result['process_rss_kib']=None
            result['process_rss_status']='sandbox_denied; use child self-reported peak'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-root',type=Path,required=True)
    parser.add_argument('--selene-root',type=Path,required=True)
    parser.add_argument('--package-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    tool=args.core_root/'tools/eval/folio-ner/shadow.py'
    assert not args.output.exists(), 'new synthetic output directory required'
    args.output.mkdir(parents=True,mode=0o700)
    # Confirm the OS policy independently of the runner's Python socket guard.
    probe=socket.socket()
    code=probe.connect_ex(('127.0.0.1',9))
    probe.close()
    assert code in (errno.EPERM,errno.EACCES), 'launch under deny-network sandbox'
    write(args.output/'network-policy.json',{'profile':'(version 1) (allow default) (deny network*)',
        'loopback_connect_errno':code,'denied':True})
    cases=[
        ('unicode','🦉 Nell crosses the opal bridge into Copperhaven.', [('Nell','writing.character'),('Copperhaven','writing.setting')]),
        ('correction','Correction: Nell stays in Copperhaven; Bram leaves.', [('Nell','writing.character'),('Copperhaven','writing.setting'),('Bram','writing.character')]),
        ('negative_editor','My editor, Rowan Ellis, checked the sentence during a meeting in Zurich.', []),
        ('decomposed','Evi waits at Cafe\u0301 Argent while Tomas approaches.', [('Evi','writing.character'),('Cafe\u0301 Argent','writing.setting'),('Tomas','writing.character')]),
        ('plain_negative','A rhythm change here would make the paragraph shorter and easier to read.', []),
        ('character_overflow','x'*4001,[]),
        ('word_overflow','word '*385,[]),
        ('token_overflow','qwertyuiopasdfghjklzxcvbnm'*80,[]),
        ('blank','',[]),
    ]
    notes=[]; gold={}; labels={}
    folio=str(uuid5(NAMESPACE_URL,'synthetic-selene-smoke-20261115'))
    for order,(label,text,annotations) in enumerate(cases):
        note_id=str(uuid5(NAMESPACE_URL,'synthetic-selene-smoke-20261115:'+label))
        notes.append({'note_id':note_id,'folio_id':folio,'capture_order':order,'local_only':True,
            'medium':'typed','transcript_model':None,'transcript_backend':None,'text':text})
        gold[note_id]=[{'start':text.index(quote),'end':text.index(quote)+len(quote),'role':kind}
                      for quote,kind in annotations]
        labels[note_id]=label
    inputs=args.output/'synthetic-notes.jsonl'
    inputs.write_text(''.join(json.dumps(n,ensure_ascii=False)+'\n' for n in notes))
    write(args.output/'synthetic-gold.json',{'kind':'authored diagnostic, not held-out or human review',
                                          'labels':labels,'annotations':gold})
    workspace=args.output/'workspace'
    commands=[]
    def cli(*arguments):
        command=[sys.executable,'-B',str(tool),*map(str,arguments)]
        p=subprocess.run(command,capture_output=True,text=True)
        commands.append({'argv':command,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        assert p.returncode==0, 'CLI failure: '+p.stderr
        return json.loads(p.stdout)
    preflight=cli('preflight','--selene-root',args.selene_root)
    freeze=cli('freeze','--input',inputs,'--workspace',workspace,'--seed','synthetic-native-smoke-20261115')
    frozen=read(workspace/'frozen.json')
    blind=read(workspace/'unaided-template.json')
    for row in blind:
        row.update(complete=True,actor='scripted synthetic gold; NOT human review',reviewed_at=stamp(),
                   mentions=gold[row['note_id']])
    unaided=args.output/'scripted-unaided.json'
    write(unaided,blind)
    command=[sys.executable,'-B',str(tool),'run','--workspace',str(workspace),
        '--model-package',str(args.package_root),'--selene-root',str(args.selene_root),'--unaided-review',str(unaided)]
    samples=[sample()]
    start=time.perf_counter()
    child=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    while True:
        try:
            stdout,stderr=child.communicate(timeout=1)
            break
        except subprocess.TimeoutExpired:
            samples.append(sample(child.pid))
            if time.perf_counter()-start>300:
                child.terminate()
                child.communicate(timeout=10)
                raise RuntimeError('synthetic smoke exceeded 300 seconds')
        except BaseException:
            child.terminate()
            child.communicate(timeout=10)
            raise
    elapsed=time.perf_counter()-start
    commands.append({'argv':command,'returncode':child.returncode,'stdout':stdout,'stderr':stderr})
    write(args.output/'commands-before-review.json',commands)
    samples.append(sample())
    for _ in range(3):
        time.sleep(1)
        samples.append(sample())
    write(args.output/'host-samples.json',samples)
    assert child.returncode==0, 'native runner failed: '+stderr
    native=json.loads(stdout)
    run=Path(native['run_directory'])
    meta=read(run/'run.json')
    sheet=read(run/'review-template.json')
    checked=0; reasons=Counter(); case_results=[]
    for row in sheet['notes']:
        ev=read(run/(row['note_id']+'.json'))
        expected=gold[row['note_id']]
        row.update(complete=True,actor='scripted synthetic gold; NOT human review',reviewed_at=stamp(),seconds=0,actions=0)
        represented=set()
        for candidate in row['candidates']:
            checked+=1
            loc=next(c['source_locator'] for c in ev['candidates'] if c['candidate_id']==candidate['candidate_id'])
            assert row['text'][loc['start']:loc['end']]==loc['quote']
            assert type(candidate['score']) in (int,float) and 0<=candidate['score']<=1
            exact=next((g for g in expected if (g['start'],g['end'])==(candidate['start'],candidate['end'])),None)
            overlapping=next((g for g in expected if max(g['start'],candidate['start'])<min(g['end'],candidate['end'])),None)
            if exact:
                candidate.update(span_verdict='exact',role=exact['role'])
                represented.add((exact['start'],exact['end'],exact['role']))
            elif overlapping:
                candidate.update(span_verdict='wrong_edges',role=overlapping['role'],
                    corrected_span={k:overlapping[k] for k in ('start','end')})
                represented.add((overlapping['start'],overlapping['end'],overlapping['role']))
            else:
                candidate.update(span_verdict='not_mention',role='outside_story' if labels[row['note_id']]=='negative_editor' else 'neither')
        row['missed']=[{**g,'entity_ref':'new'} for g in expected if (g['start'],g['end'],g['role']) not in represented]
        if ev['status']=='refused':
            reasons[ev['refusal_code']]+=1
        case_results.append({'label':labels[row['note_id']],'status':ev['status'],
            'refusal_code':ev.get('refusal_code'),'candidates':len(ev['candidates']),
            'inference_seconds':ev.get('inference_seconds'),'preflight':ev.get('preflight')})
    assert native['read']==5 and native['refused']==4, native
    assert reasons['source_too_long']==1 and reasons['source_word_budget']==1 and reasons['source_token_budget']==1, reasons
    assert sum(reasons.values())==4 and checked>0
    reviews=args.output/'scripted-review.json'
    write(reviews,sheet)
    imported=cli('review','--workspace',workspace,'--run',run,'--reviews',reviews)
    tally=cli('tally','--workspace',workspace,'--run',run,'--reviews',imported['review_snapshot'])
    repeated=cli('review','--workspace',workspace,'--run',run,'--reviews',reviews)
    assert repeated['review_snapshot']!=imported['review_snapshot']
    assert Path(imported['review_snapshot']).exists()
    serialized=json.dumps(tally)
    for quote in ('Nell','Copperhaven','Rowan Ellis','Cafe','Tomas','scripted synthetic gold'):
        assert quote not in serialized
    assert sum(v['counts']['notes'] for v in tally['splits'].values())==9
    assert 'torch' not in sys.modules, 'driver itself must not retain the model'
    write(args.output/'commands.json',commands)
    summary={'kind':'synthetic native smoke; NOT a benchmark, held-out result or human review',
        'completed_at':stamp(),'python':sys.version,'machine':os.uname().machine,
        'driver_sha256':sha(Path(__file__)),'preflight':preflight,'freeze':freeze,'native':native,
        'returncode':child.returncode,'wall_seconds':elapsed,'load_seconds':meta['load_seconds'],
        'peak_rss_bytes_macos':meta['peak_rss_bytes_macos'],'profile_digest':meta['profile_digest'],
        'manifest_sha256':meta['manifest_sha256'],'code':meta['code'],
        'cases':case_results,'checked_candidates':checked,'refusals':dict(reasons),
        'scripted_review_only':True,'review_snapshots_preserved':True,'tallies_text_free':True,
        'network_policy':'macOS deny network* inherited by subprocess; loopback EPERM verified',
        'model_process_exited':child.returncode==0,'retained_model_in_driver':False,
        'limits':['single laptop smoke on authored examples, not quality acceptance',
                  'system swap samples reflect all applications, not model-attributable swap',
                  'no model unload/reload trial or Crossroads host-fit claim',
                  'no real notes, DB/ActionRuns, ASGI/Switchboard route or production deployment'],
        'installed_distributions':sorted({d.metadata['Name']:d.version for d in importlib.metadata.distributions()}.items())}
    write(args.output/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ('completed_at','returncode','wall_seconds','load_seconds',
        'peak_rss_bytes_macos','checked_candidates','refusals','tallies_text_free','model_process_exited')},indent=2))


if __name__=='__main__':
    main()
