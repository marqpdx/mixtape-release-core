import copy
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch
from jsonschema import ValidationError
from shuttle.interpretation.contract import validate_findings, source_digest


class ContractTests(TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent.parent / 'interpretation' / 'spoken_choirs.findings.json').read_text())
        self.result = self.fixture['findings']
        self.sources = self.fixture['sources']

    def test_real_telling_and_all_six_shapes_validate(self):
        self.assertEqual(validate_findings(self.result, self.sources), self.result)
        self.assertEqual(len({s['shape_id'] for s in self.result['sightings']}), 6)

    def test_story_and_source_are_never_normalized(self):
        original = copy.deepcopy(self.fixture)
        validate_findings(self.result, self.sources)
        self.assertEqual(original, self.fixture)
        story = next(s for s in self.result['sightings'] if s['shape_id'] == 'shuttle.story')
        self.assertTrue(story['text'].endswith('under the...'))

    def test_invalid_source_and_rewritten_story_are_rejected(self):
        for mutation in ['quote', 'story', 'source', 'offset', 'reference', 'shape', 'duplicate']:
            with self.subTest(mutation=mutation):
                result = copy.deepcopy(self.result)
                if mutation == 'quote': result['sightings'][0]['source_locator'][0]['quote'] = 'invented'
                if mutation == 'story': next(s for s in result['sightings'] if s['shape_id'] == 'shuttle.story')['text'] += 'a roof.'
                if mutation == 'source': result['sightings'][0]['source_locator'][0]['source_ref'] = 'someone-else'
                if mutation == 'offset': result['sightings'][0]['source_locator'][0]['start'] += 1
                if mutation == 'reference': next(s for s in result['sightings'] if s['shape_id'] == 'shuttle.adjacency')['ends'][0] = 'locale-portland'
                if mutation == 'shape': result['sightings'][0]['shape_version'] = '999'
                if mutation == 'duplicate': result['sightings'].append(copy.deepcopy(result['sightings'][0]))
                with self.assertRaises(ValidationError): validate_findings(result, self.sources)

    def test_missing_shapes_are_not_fabricated_to_match_fixture_counts(self):
        result = copy.deepcopy(self.result)
        result['sightings'] = [s for s in result['sightings'] if s['shape_id'] == 'shuttle.weave']
        for key in ['thing_ids', 'place_ids', 'idea_ids', 'adjacency_ids', 'story_ids']:
            result['sightings'][0][key] = []
        result['questions'] = []
        validate_findings(result, self.sources)

    def test_digest_binds_exact_text_and_each_revision(self):
        original = source_digest(self.sources)
        sources = copy.deepcopy(self.sources)
        sources[0]['text'] += ' '
        self.assertNotEqual(source_digest(sources), original)
        sources = copy.deepcopy(self.sources)
        sources[0]['source_revision'] += 1
        self.assertNotEqual(source_digest(sources), original)

    def test_unicode_code_points_not_utf16(self):
        result = copy.deepcopy(self.result)
        sources = copy.deepcopy(self.sources)
        sources[0]['text'] = '🎵' + sources[0]['text']
        def shift(value):
            if isinstance(value, dict):
                if {'start', 'end', 'quote'}.issubset(value):
                    value['start'] += 1
                    value['end'] += 1
                for child in value.values(): shift(child)
            elif isinstance(value, list):
                for child in value: shift(child)
        shift(result)
        validate_findings(result, sources)

    def test_shared_claude_runner_can_disable_tools_and_use_configured_home(self):
        from claude.service import run_blocking
        completed=MagicMock(returncode=0,stdout='{"result":"ok"}',stderr='')
        with patch('claude.service.subprocess.run',return_value=completed) as run:
            result=run_blocking('bounded input',cwd='/srv/private-weaver',run_as_user='weaver',home_dir='/srv/private-weaver',tools='')
        self.assertEqual(result.output,'ok')
        command=run.call_args.args[0]
        self.assertEqual(command[command.index('--tools')+1],'')
        self.assertIn('--strict-mcp-config',command)
        self.assertEqual(run.call_args.kwargs['env']['HOME'],'/srv/private-weaver')
