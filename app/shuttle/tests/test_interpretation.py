import copy
import json
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from initiatives.models import ActionRun, ActionRunStatus
from tenant_runtime.models import TenantClaudeRuntime
from writing.models import Seed
from shuttle.interpretation import lifecycle
from shuttle.interpretation.contract import CAPABILITY
from shuttle.interpretation.tasks import apply_interpretation, run_cloud_interpretation


@override_settings(ROOT_URLCONF='shuttle.api.urls', SHUTTLE_INTERPRET_CLOUD=True)
class InterpretationTests(TestCase):
    def setUp(self):
        self.author = get_user_model().objects.create_superuser(username='shuttle-weaver', email='weaver@example.test', password='test')
        self.other = get_user_model().objects.create_user(username='shuttle-other', email='other@example.test', password='test')
        self.seed = Seed.objects.create(author=self.author, body_text='I found a choir and remembered another.', kind='text', status='ready')
        self.client = APIClient()
        self.client.force_authenticate(self.author)
        self.runtime = TenantClaudeRuntime.objects.create(
            tenant_content_type=ContentType.objects.get_for_model(self.author), tenant_object_id=self.author.pk,
            linux_user='shuttle-weaver', home_dir='/home/shuttle-weaver',
            status=TenantClaudeRuntime.STATUS_READY, allowed_ai_modes=[CAPABILITY])

    def begin(self, request_id=None):
        return lifecycle.begin(author=self.author, request_id=request_id or uuid4(), seed_id=self.seed.pk, client='phone')

    def execute(self, state, request_id=None, consent=True):
        with self.captureOnCommitCallbacks(execute=True):
            return lifecycle.execute(author=self.author, action_run_id=state['weave_action_run_id'],
                request_id=request_id or uuid4(), expected_revision=state['revision'], digest=state['source_digest'], consent=consent)

    def test_duplicate_start_reuses_one_envelope_and_keeps_platform_tenant(self):
        request_id = uuid4()
        first, second = self.begin(request_id), self.begin(request_id)
        self.assertEqual(first['weave_action_run_id'], second['weave_action_run_id'])
        self.assertEqual(ActionRun.objects.filter(tool_name='shuttle.weave').count(), 1)
        parent = ActionRun.objects.get(pk=first['weave_action_run_id'])
        self.assertNotEqual(parent.tenant_id, self.author.pk)
        self.assertEqual(parent.initiator_id, str(self.author.pk))

    def test_no_dispatch_without_source_bound_consent(self):
        state = self.begin()
        with patch('shuttle.interpretation.lifecycle.celery_app.send_task') as send:
            with self.assertRaises(lifecycle.InterpretationError): self.execute(state, consent=False)
            send.assert_not_called()
        self.assertEqual(ActionRun.objects.filter(parent_action_id=state['weave_action_run_id']).count(), 0)

    def test_approval_recorded_before_dispatch_and_idempotent(self):
        state, request_id = self.begin(), uuid4()
        def dispatched(*args, **kwargs):
            child = ActionRun.objects.get(pk=kwargs['kwargs']['action_run_id'])
            self.assertTrue(child.cloud_approved)
            self.assertEqual(child.approval_payload['source_digest'], state['source_digest'])
            self.assertEqual(child.approval_payload['author_id'], str(self.author.pk))
            self.assertEqual(child.parent_action_id, uuid4_from(state['weave_action_run_id']))
        with patch('shuttle.interpretation.lifecycle.celery_app.send_task', side_effect=dispatched) as send:
            first = self.execute(state, request_id)
            second = self.execute(state, request_id)
            self.assertEqual(first['execution_action_run_id'], second['execution_action_run_id'])
            self.assertEqual(send.call_count, 1)
        self.assertEqual(ActionRun.objects.get(pk=state['weave_action_run_id']).status, ActionRunStatus.PENDING)

    def test_missing_runtime_and_disallowed_mode_never_dispatch(self):
        state = self.begin()
        self.runtime.allowed_ai_modes = []
        self.runtime.save()
        with patch('shuttle.interpretation.lifecycle.celery_app.send_task') as send:
            with self.assertRaises(lifecycle.InterpretationError) as err: self.execute(state)
            self.assertEqual(err.exception.code, 'mode_not_allowed')
            self.runtime.delete()
            with self.assertRaises(lifecycle.InterpretationError) as err: self.execute(state)
            self.assertEqual(err.exception.code, 'runtime_missing')
            send.assert_not_called()

    def test_source_and_weave_are_self_authority(self):
        state = self.begin()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/weaves/{state['weave_action_run_id']}/").status_code, 404)
        response = self.client.post('/weaves/', {'request_id':str(uuid4()),'seed_id':str(self.seed.pk),'client':'phone'})
        self.assertEqual(response.status_code, 404)

    def test_correction_preserves_original_and_supersedes_old_callback(self):
        state = self.begin()
        with patch('shuttle.interpretation.lifecycle.celery_app.send_task'):
            running = self.execute(state)
        corrected = lifecycle.correct(author=self.author, action_run_id=state['weave_action_run_id'],
            request_id=uuid4(), expected_revision=0, text='Actually, they are not connected.')
        self.assertEqual(corrected['revision'], 1)
        self.assertEqual(corrected['sources'][0]['text'], self.seed.body_text)
        child = ActionRun.objects.get(pk=running['execution_action_run_id'])
        child.status, child.error_payload = ActionRunStatus.FAILED, {'error':'timeout'}
        child.save()
        apply_interpretation(str(child.pk))
        parent = ActionRun.objects.get(pk=state['weave_action_run_id'])
        self.assertEqual(lifecycle.snapshot(parent)['revision'], 1)
        self.assertIsNone(lifecycle.snapshot(parent)['error'])
        self.assertIsNone(lifecycle.snapshot(parent)['findings'])
        with self.assertRaises(lifecycle.InterpretationError):
            lifecycle.correct(author=self.author, action_run_id=str(parent.pk), request_id=uuid4(), expected_revision=0, text='stale')

    def test_cloud_worker_requires_gate_proof_even_with_consent(self):
        state = self.begin()
        with patch('shuttle.interpretation.lifecycle.celery_app.send_task'):
            running = self.execute(state)
        child = ActionRun.objects.get(pk=running['execution_action_run_id'])
        child.status = ActionRunStatus.RUNNING
        child.save()
        with patch('claude.service.run_blocking') as model:
            run_cloud_interpretation(action_run_id=str(child.pk))
            model.assert_not_called()
        child.refresh_from_db()
        self.assertEqual(child.error_payload['error'], 'cloud_approval_required')

    def test_correction_retry_cannot_change_text_under_the_same_request(self):
        state, request_id = self.begin(), uuid4()
        kwargs = dict(author=self.author, action_run_id=state['weave_action_run_id'],
            request_id=request_id, expected_revision=0)
        first=lifecycle.correct(**kwargs,text='Actually, Low Bar Chorale.')
        retry=lifecycle.correct(**kwargs,text='Actually, Low Bar Chorale.')
        self.assertEqual(first['revision'],retry['revision'])
        with self.assertRaises(lifecycle.InterpretationError) as err:
            lifecycle.correct(**kwargs,text='Different correction.')
        self.assertEqual(err.exception.code,'request_conflict')

    def test_success_uses_exact_person_runtime_and_only_completes_child(self):
        fixture=json.loads((Path(__file__).parent.parent/'interpretation'/'spoken_choirs.findings.json').read_text())
        self.seed.body_text=fixture['sources'][0]['text']
        self.seed.save()
        state=self.begin()
        with patch('shuttle.interpretation.lifecycle.celery_app.send_task'):
            running=self.execute(state)
        child=ActionRun.objects.get(pk=running['execution_action_run_id'])
        findings=copy.deepcopy(fixture['findings'])
        old_ref=fixture['sources'][0]['source_ref']
        new_ref=state['sources'][0]['source_ref']
        def rebind(value):
            if isinstance(value,dict):
                if value.get('source_ref')==old_ref: value['source_ref']=new_ref
                for nested in value.values(): rebind(nested)
            elif isinstance(value,list):
                for nested in value: rebind(nested)
        rebind(findings)
        child.status=ActionRunStatus.RUNNING
        child.result_payload={'dispatch':{'cloud_approved':True,'source_digest':state['source_digest'],'revision':0}}
        child.save()
        from claude.service import ClaudeResult
        with patch('claude.service.run_blocking',return_value=ClaudeResult(output=json.dumps(findings),elapsed_ms=10)) as model:
            run_cloud_interpretation(action_run_id=str(child.pk))
        self.assertEqual(model.call_args.kwargs['run_as_user'],self.runtime.linux_user)
        self.assertEqual(model.call_args.kwargs['home_dir'],self.runtime.home_dir)
        self.assertEqual(model.call_args.kwargs['tools'],'')
        parent=ActionRun.objects.get(pk=state['weave_action_run_id'])
        child.refresh_from_db()
        self.assertEqual(child.status,ActionRunStatus.SUCCEEDED)
        self.assertEqual(parent.status,ActionRunStatus.PENDING)
        response=lifecycle.snapshot(parent)
        self.assertEqual(response['findings']['sightings'],findings['sightings'])
        self.assertEqual(response['status'],'succeeded')


def uuid4_from(value):
    from uuid import UUID
    return UUID(value)
