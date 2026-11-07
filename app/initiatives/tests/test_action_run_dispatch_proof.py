"""Exercise the real two-PATCH Switchboard handoff and its consent boundary."""
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from initiatives.api.serializers import ActionRunPatchSerializer
from initiatives.api.views import ActionRunDetailView
from initiatives.models import ActionRun, ActionRunStatus


def child_run(status=ActionRunStatus.RUNNING):
    run=ActionRun(id=uuid4(), tool_name='capability.shuttle_weave_interpret',
        service_name='switchboard', execution_mode='cloud', status=status,
        parent_action_id=uuid4(), cloud_approved=True, initiator_id=str(uuid4()),
        tenant_id=uuid4(), tenant_namespace='platform:test', initiator_type='human',
        request_payload={'capability_payload':{'source_digest':'a'*64,'revision':0}})
    run.approval_payload={'author_id':run.initiator_id,
        'weave_action_run_id':str(run.parent_action_id),'execution_action_run_id':str(run.pk),
        'capability':'shuttle_weave_interpret','source_digest':'a'*64,'revision':0}
    return run


def gate_patch():
    return {'status':'running','result_payload':{'dispatch':{'cloud_approved':True,
        'capability':'shuttle_weave_interpret','source_digest':'a'*64,'revision':0}}}


class DispatchProofValidationTests(SimpleTestCase):
    def valid(self, run, data):
        return ActionRunPatchSerializer(run,data=data,partial=True).is_valid()

    def test_bound_gate_accepts_pending_or_running_and_identical_proof_replay(self):
        for status in ['pending','running']:
            run=child_run(status)
            self.assertTrue(self.valid(run,gate_patch()))
            run.result_payload=gate_patch()['result_payload']
            self.assertTrue(self.valid(run,gate_patch()))

    def test_running_results_and_bare_self_transition_remain_forbidden(self):
        for data in [{'status':'running'},
                {'status':'running','result_payload':{'result':{'findings':[]}}},
                {'status':'running','result_payload':{'dispatch':{'cloud_approved':True}}}]:
            self.assertFalse(self.valid(child_run(),data))

    def test_dispatch_proof_cannot_grant_or_change_prior_consent(self):
        for field, value in [('cloud_approved',False),('execution_mode','local'),
                ('service_name','other'),('tool_name','capability.other'),
                ('initiator_id',str(uuid4())),('parent_action_id',None)]:
            with self.subTest(field=field):
                run=child_run();setattr(run,field,value)
                self.assertFalse(self.valid(run,gate_patch()))
        for field in ['author_id','weave_action_run_id','execution_action_run_id',
                'capability','source_digest','revision']:
            run=child_run();run.approval_payload[field]='wrong'
            self.assertFalse(self.valid(run,gate_patch()))

    def test_mismatched_request_digest_or_revision_refused(self):
        for field in ['source_digest','revision']:
            run=child_run();run.request_payload['capability_payload'][field]='wrong'
            self.assertFalse(self.valid(run,gate_patch()))

    def test_gate_shape_types_and_extra_results_refused(self):
        for field,value in [('cloud_approved','true'),('revision',False),
                ('source_digest','x'*64),('capability','other')]:
            data=gate_patch();data['result_payload']['dispatch'][field]=value
            self.assertFalse(self.valid(child_run(),data))
        data=gate_patch();data['result_payload']['result']={'findings':[]}
        self.assertFalse(self.valid(child_run(),data))

    def test_missing_approval_and_changed_existing_proof_refused(self):
        run=child_run();run.approval_payload=None
        self.assertFalse(self.valid(run,gate_patch()))
        run=child_run();run.result_payload={'dispatch':{'revision':12}}
        self.assertFalse(self.valid(run,gate_patch()))

    def test_terminal_runs_stay_closed(self):
        for status in ['succeeded','failed']:
            self.assertFalse(self.valid(child_run(status),gate_patch()))

    def test_error_or_completion_time_forbidden_on_gate_record(self):
        for field,value in [('error_payload',{'error':'bad'}),
                ('completed_at','2026-11-07T00:00:00Z')]:
            data=gate_patch();data[field]=value
            self.assertFalse(self.valid(child_run(),data))

    def test_ordinary_terminal_updates_unchanged(self):
        self.assertTrue(self.valid(child_run(),{'status':'succeeded','result_payload':{'result':1}}))
        self.assertTrue(self.valid(child_run(),{'status':'failed','error_payload':{'error':'timeout'}}))


class DispatchProofPatchTests(TestCase):
    def setUp(self):
        self.run=child_run('pending')
        parent=ActionRun.objects.create(id=self.run.parent_action_id,tool_name='shuttle.weave',
            initiator_id=self.run.initiator_id,initiator_type='human',
            tenant_id=self.run.tenant_id,tenant_namespace=self.run.tenant_namespace)
        self.run.save()

    def patch_run(self,data):
        request=APIRequestFactory().patch('/',data,format='json')
        force_authenticate(request,user=SimpleNamespace(is_authenticated=True, pk=uuid4()))
        # Keep this regression focused on the real PATCH serializer/persistence;
        # the existing service JWT authentication/scope boundary is unchanged.
        with patch('initiatives.api.views.HasOrchestrationWriteScope.has_permission',return_value=True):
            return ActionRunDetailView.as_view()(request,action_run_id=self.run.pk)

    def test_real_start_then_gate_patch_persists_before_worker_can_run(self):
        self.assertEqual(self.patch_run({'status':'running'}).status_code,200)
        response=self.patch_run(gate_patch())
        self.assertEqual(response.status_code,200,response.data)
        self.run.refresh_from_db()
        self.assertEqual(self.run.status,'running')
        self.assertEqual(self.run.result_payload,gate_patch()['result_payload'])
        self.assertTrue(self.run.cloud_approved)
        self.assertIsNone(self.run.completed_at)
        self.assertEqual(self.patch_run(gate_patch()).status_code,200)

    def test_late_gate_patch_cannot_reopen_failed_run(self):
        self.assertEqual(self.patch_run({'status':'failed','error_payload':{'error':'timeout'}}).status_code,200)
        self.assertEqual(self.patch_run(gate_patch()).status_code,400)
        self.run.refresh_from_db()
        self.assertEqual(self.run.status,'failed')
        self.assertIsNone(self.run.result_payload)
