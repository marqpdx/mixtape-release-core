import json
import unittest
from run_m3_qwen import validate_answer, messages_for, assert_case

class QwenHarnessTests(unittest.TestCase):
    def answer(self,quote='Mara',occurrence=1):
        return json.dumps({'decision':'classified','label':'writing.character',
            'evidence':[{'quote':quote,'occurrence':occurrence}],'uncertain':[]})

    def test_original_unicode_and_occurrence(self):
        text='Mara met Mara at Café.'
        _,spans=validate_answer(self.answer(occurrence=2),text)
        self.assertEqual(spans[0]['start'],9)
        _,spans=validate_answer(self.answer('Café'),text)
        self.assertEqual(text[spans[0]['start']:spans[0]['end']],'Café')

    def test_invented_or_normalized_quote_rejected(self):
        for quote in ['Lucy','Café']:
            with self.assertRaises(ValueError): validate_answer(self.answer(quote),'Café Mara')

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError): validate_answer('{"label":"none","label":"writing.scene"}','x')

    def test_abstention_not_none(self):
        with self.assertRaises(ValueError):
            validate_answer(json.dumps({'decision':'abstained','label':'none',
                'evidence':[{'quote':'Mara','occurrence':1}],'uncertain':['unclear']}),'Mara')

    def test_gold_excluded(self):
        case={'source_ref':'s','source_revision':0,'source_sha256':'h','text':'Mara',
            'target':{'start':0,'end':4,'quote':'Mara'},'expected_label':'SECRET_GOLD',
            'rationale':'SECRET_REASON','evidence_proposals':['SECRET_EVIDENCE']}
        prompt=json.dumps(messages_for(case,{}))
        self.assertNotIn('SECRET_',prompt)

    def test_approved_sources_and_spans(self):
        from pathlib import Path
        corpus=json.loads(Path(__file__).with_name('m3-cases.proposed.json').read_text())
        self.assertEqual(corpus['status'],'approved_frozen')
        self.assertEqual(len(corpus['units']),16)
        for case in corpus['units']: assert_case(case)
        juno=next(c for c in corpus['units'] if c['id']=='m3-character-juno')
        self.assertIn('pockets their hands',juno['text'])
