"""Build an unapplied canonical activation diff and rehearse it in scratch only."""
from pathlib import Path
import difflib
import argparse
import socket
import hashlib
import json
import subprocess
import tempfile
from unittest.mock import patch

from heddle.bundle import digest, schema_validator, check_schema_references
from heddle.generate_bundle import generate
from folio.interpretation import strategy

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--release-root', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args=parser.parse_args()
RELEASE=args.release_root.resolve()
CANON=RELEASE/'puddlejump/reference/contour'
DRAFT=CANON/'_proposed/folio-recognition-0.2.0'
OUT=args.output_dir.resolve()
OUT.mkdir(parents=True,exist_ok=True)

def refuse_network(*args,**kwargs):
    raise AssertionError('Schema review must not access the network')

socket.socket.connect=refuse_network
socket.socket.connect_ex=refuse_network
socket.getaddrinfo=refuse_network
source_commit=subprocess.check_output(['git','-C',str(RELEASE/'puddlejump'),'rev-parse','HEAD'],text=True).strip()
original_bundle=generate(CANON,source_commit)
assert original_bundle["library_version"] == "0.4.6", "Canonical activation baseline changed; re-review before generating a patch"
proposed={}
retained={}
for name in ('character','setting'):
    for suffix in ('schema.json','shape.yaml','template.md','extraction.md','validation.md'):
        original=f'writing/{name}.{suffix}'
        archive=f'writing/versions/{name}.0.1.0.{suffix}'
        data=(CANON/original).read_text()
        proposed[archive]=data
        retained[original]=hashlib.sha256(data.encode()).hexdigest()
    proposed[f'writing/{name}.schema.json']=(DRAFT/f'writing/{name}-0.2.0.schema.json').read_text()
    meta=(CANON/f'writing/{name}.shape.yaml').read_text()
    meta=meta.replace('version: 0.1.0','version: 0.2.0',1).replace('    const: 0.1.0','    const: 0.2.0',1)
    meta=meta.replace('- confidence\n- source_locator','- provenance\n- source_locator',1)
    meta=meta.replace('optional_fields:\n','optional_fields:\n- confidence\n',1)
    meta=meta.replace('companion_files:\n','  provenance:\n    $ref: urn:contour:shared.sighting_provenance:0.1.0\nconfidence_rule: Required only for model provenance; absent for person and dictionary provenance.\ncompanion_files:\n',1)
    proposed[f'writing/{name}.shape.yaml']=meta
    for kind in ('template','extraction','validation'):
        text=(CANON/f'writing/{name}.{kind}.md').read_text().replace('0.1.0','0.2.0')
        if kind=='template':
            text += '\nProvenance: {{provenance}}\n\nConfidence is present only for model origin; person and Dictionary origins have no fabricated confidence.\n'
        elif kind=='extraction':
            text=text.replace('Record Shape id and version, confidence, and every unresolved detail','Record Shape id and version, model-only confidence, and every unresolved detail')
            text += '\nCore binds provenance from the actual execution, authenticated human operation or immutable Dictionary entry revision. Raw NER scores are recognition evidence, never automatic canonical confidence. Recognition alone creates no Sighting or Entity.\n'
        else:
            text += '\n6. Resolve shared schema URNs only from the pinned local bundle and enforce UUID/date-time formats. Require confidence only for model-origin Sightings; prohibit it for person/Dictionary origins. Core verifies provenance against actual execution/actor/operation/entry records.\n'
        proposed[f'writing/{name}.{kind}.md']=text
for name in ('sighting_provenance','dictionary_entry'):
    proposed[f'shared/{name}.schema.json']=(DRAFT/f'shared/{name}.schema.json').read_text()
for name in ('fiction-note-recognition.strategy.yaml','fiction-note-recognition.md'):
    proposed[f'writing/strategies/{name}']=(DRAFT/f'writing/strategies/{name}').read_text()
manifest=(CANON/'manifest.yaml').read_text()
for name in ('character','setting'):
    old=f'    - id: writing.{name}\n      version: 0.1.0'
    assert manifest.count(old)==1
    manifest=manifest.replace(old,old.replace('0.1.0','0.2.0'))
manifest=manifest.replace('library_version: 0.4.6','library_version: 0.4.7',1)
definitions='''schema_definitions:
  - id: shared.sighting_provenance
    version: 0.1.0
    schema_file: shared/sighting_provenance.schema.json
  - id: shared.dictionary_entry
    version: 0.1.0
    schema_file: shared/dictionary_entry.schema.json

'''
manifest=manifest.replace('verticals:\n',definitions+'verticals:\n',1)
marker='        prose_file: puddlejump/reference/contour/writing/strategies/fiction-note-reading.md\n'
assert manifest.count(marker)==1
manifest=manifest.replace(marker,marker+'''
      - id: writing.fiction_note_recognition
        version: 0.1.0
        status: draft
        domain: writing
        source_shapes: []
        primary_target: null
        secondary_targets: [writing.character, writing.setting]
        sectioning: whole_document
        extraction_grain: whole_note
        contract_file: puddlejump/reference/contour/writing/strategies/fiction-note-recognition.strategy.yaml
        prose_file: puddlejump/reference/contour/writing/strategies/fiction-note-recognition.md
''',1)
proposed['manifest.yaml']=manifest
readme=(CANON/'writing/README.md').read_text()
readme += '''
## Recognition and retained versions

Character and Setting 0.2.0 add shared provenance: model, person or Dictionary.
Only model-origin Sightings carry canonical confidence. Raw NER scores remain
recognition evidence and do not create Sightings or Entities automatically.
The 0.1.0 schemas/descriptors/guidance remain under `versions/`, byte unchanged;
the composed `writing.fiction_note_reading` 0.1.0 remains pinned to those versions.
`writing.fiction_note_recognition` 0.1.0 is separate: successful actual steps still
present partial coverage (`recognition_only`, semantic interpretation `not_run`).
Shared definitions resolve only from the generated local bundle. Activation of
schemas does not register an execution capability or approve a phone build.
'''
proposed['writing/README.md']=readme
shared=(CANON/'shared/README.md')
proposed['shared/README.md']=(shared.read_text() if shared.exists() else '# Shared schema definitions\n')+'''\n`shared.sighting_provenance` 0.1.0 and `shared.dictionary_entry` 0.1.0 are schema definitions, not persistence/API wrappers or an automatic Entity-creation mechanism. Their versioned URNs resolve from the release-local bundle.\n'''
report={'status':'unapplied_review_only','canonical_source_commit':source_commit,
        'current_library_version':original_bundle['library_version'],'proposed_library_version':'0.4.7',
        'proposed_files':sorted(proposed),'retained_original_sha256':retained,'checks':[]}
with tempfile.TemporaryDirectory(prefix='selene-contour-review-') as directory:
    root=Path(directory)
    # Reconstruct selected current canonical files only; never copy unrelated folders.
    for name,entry in original_bundle['files'].items():
        dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(entry['text'])
    for name,text in proposed.items():
        dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
    for name,oldhash in retained.items():
        stem,suffix=name.rsplit('/',1)
        shape,tail=suffix.split('.',1)
        archive=f'{stem}/versions/{shape}.0.1.0.{tail}'
        assert hashlib.sha256((root/archive).read_bytes()).hexdigest()==oldhash
    bundle=generate(root,source_commit)
    bundle['digest']=digest(bundle)
    check_schema_references(bundle)
    with patch.object(strategy,'_load',return_value=bundle):
        assert ('writing.character','character') in strategy.dependencies()['cues']
    report['checks'] += ['retained 0.1.0 files byte-identical','all shared refs resolve offline','composed Strategy still reads retained 0.1.0 descriptors']
    span={'source_ref':'fixture','source_revision':0,'start':0,'end':4,'quote':'Mara'}
    good=0;bad=0
    for shape in ('character','setting'):
        schema=json.loads(bundle['files'][bundle['schemas'][f'writing.{shape}@0.2.0']]['text'])
        validator=schema_validator(schema,bundle=bundle)
        for provenance in (
            {'kind':'model','model_id':'synthetic-model','model_revision':'synthetic-revision','execution_action_run_id':'00000000-0000-0000-0000-000000000001'},
            {'kind':'person','actor_id':'00000000-0000-0000-0000-000000000001','operation_id':'00000000-0000-0000-0000-000000000002','recorded_at':'2026-11-10T00:00:00Z'},
            {'kind':'dictionary','entry_id':'00000000-0000-0000-0000-000000000001','entry_revision':1},
        ):
            data={'shape_id':f'writing.{shape}','shape_version':'0.2.0','sighting_id':'fixture',
                'name_as_said':'Mara','source_locator':[span],'uncertain':[],'provenance':provenance}
            if provenance['kind']=='model': data['confidence']='medium'
            validator.validate(data);good+=1
            wrong=json.loads(json.dumps(data))
            if provenance['kind']=='model':del wrong['confidence']
            else:wrong['confidence']='medium'
            assert list(validator.iter_errors(wrong));bad+=1
            if provenance['kind']=='person':
                for field,value in [('actor_id','not-a-uuid'),('recorded_at','2026-02-30T00:00:00Z'),('recorded_at','2026-11-10T00:00:00+03:00')]:
                    wrong=json.loads(json.dumps(data));wrong['provenance'][field]=value
                    assert list(validator.iter_errors(wrong));bad+=1
    dictionary=json.loads((root/'shared/dictionary_entry.schema.json').read_text())
    record={'entry_id':'00000000-0000-0000-0000-000000000001','revision':1,
        'shape_id':'writing.character','shape_version':'0.2.0','names':{'main':'Mara','variants':[]},
        'provenance':{'kind':'person','actor_id':'00000000-0000-0000-0000-000000000001','operation_id':'00000000-0000-0000-0000-000000000002','recorded_at':'2026-11-10T00:00:00Z'}}
    schema_validator(dictionary,bundle=bundle).validate(record);good+=1
    report['schema_cases']={'accepted':good,'rejected':bad}
    report['checks'].append('actual draft schemas enforce provenance, conditional confidence, UUID and UTC date-time')
    report['review_bundle_digest']=bundle['digest']
    (OUT/'review-contour-bundle.json').write_text(json.dumps(bundle,indent=2)+'\n')
patches=[]
for name,text in sorted(proposed.items()):
    source=CANON/name
    old=source.read_text() if source.exists() else ''
    prefix='reference/contour/'+name
    patches.extend(difflib.unified_diff(old.splitlines(keepends=True),text.splitlines(keepends=True),
        fromfile='a/'+prefix if source.exists() else '/dev/null',tofile='b/'+prefix))
content=''.join(patches)
(OUT/'contour-activation.patch').write_text(content)
report['activation_patch_sha256']=hashlib.sha256(content.encode()).hexdigest()
(OUT/'activation-review.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
