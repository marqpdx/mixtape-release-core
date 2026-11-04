import unittest
from run_m3_gliner import sentence, classify

class M3Tests(unittest.TestCase):
    def test_sentence_keeps_offsets(self):
        text='Title. Mara returns. Next.'
        passage,offset=sentence(text,7,11)
        self.assertEqual(passage[7-offset:11-offset],'Mara')
        self.assertEqual(passage,'Mara returns. ')

    def test_none_when_no_match(self):
        self.assertEqual(classify([],0,4),'none')

    def test_neighbour_is_not_evidence(self):
        self.assertEqual(classify([{'start':5,'end':9,'label':'character','score':0.9}],0,4),'none')

    def test_tightest_containing_span_precedes_highest_score(self):
        candidates=[{'start':0,'end':15,'label':'scene','score':0.99},
                    {'start':2,'end':6,'label':'character','score':0.6}]
        self.assertEqual(classify(candidates,2,6),'writing.character')
