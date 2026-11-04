import json
from pathlib import Path
import unittest
from adapter import recognize, validate_response
from model_adapters import LocalModels, GLINER_REVISION


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.request = json.loads((Path(__file__).parent/'cases.jsonl').read_text().splitlines()[0])['request']
        self.adapter = LocalModels.__new__(LocalModels)
        self.adapter.backend = 'gliner'
        self.adapter.producer = {'kind':'model','id':'urchade/gliner_small-v2.1','version':'0.2.30','model_revision':GLINER_REVISION}

    def test_empty_ner_keeps_baseline_cues_and_valid_identity(self):
        self.adapter.entities = lambda text: []
        response, _ = self.adapter.recognize(self.request)
        self.assertEqual(response, recognize(self.request))

    def test_model_span_is_exact_and_provisional(self):
        self.adapter.entities = lambda text: [{'start':0,'end':1,'label':'character','score':0.7}]
        response, _ = self.adapter.recognize(self.request)
        validate_response(self.request,response)
        candidate = response['candidates'][-1]
        self.assertEqual(candidate['source_locator']['quote'],self.request['source']['text'][:1])
        self.assertTrue(candidate['uncertain'])
        self.assertEqual(candidate['producer']['model_revision'],GLINER_REVISION)

    def test_invalid_model_span_fails_instead_of_clipping(self):
        self.adapter.entities = lambda text: [{'start':-1,'end':9999,'label':'character','score':0.7}]
        with self.assertRaises(ValueError): self.adapter.recognize(self.request)

    def test_rewritten_quote_fails(self):
        self.adapter.entities = lambda text: [{'start':0,'end':1,'text':'changed','label':'character','score':0.7}]
        with self.assertRaises(ValueError): self.adapter.recognize(self.request)

    def test_spacy_mapping_does_not_claim_scene_extraction(self):
        from model_adapters import SPACY_LABELS
        self.assertNotIn('writing.scene',SPACY_LABELS.values())
