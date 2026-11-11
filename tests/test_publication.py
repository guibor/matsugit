import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit import publication as p
from matsugit.core import Error


class PublicationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, MATSUGIT_PUBLICATION_STATE=str(self.root/'state'))
        env.start(); self.addCleanup(env.stop)
        self.source = self.root/'deck.md'; self.source.write_text('Private synthetic draft')
        self.sha = 'a'*40
        self.plan = dict(provider='gitlab', project_url='https://git.example.invalid/team/docs',
                         branch='main', target='demo', source_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest())

    def record(self, **kwargs):
        return p.record(self.source, dict(self.plan, **kwargs), self.sha)

    def test_receipt_is_private_and_local_read_never_calls_provider(self):
        with patch.object(p, 'api', side_effect=AssertionError('No network')):
            self.assertEqual(p.status(self.source)['stage'], 'local')
            self.record()
            self.assertEqual(p.status(self.source)['revision'], self.sha)
            self.assertEqual(p.receipt_path(self.source).stat().st_mode & 0o777, 0o600)
            self.assertNotIn(self.source.read_text(), p.receipt_path(self.source).read_text())
            link = self.root/'alias.md'; link.symlink_to(self.source)
            self.assertEqual(p.status(link)['revision'], self.sha)

    def test_gitlab_success_is_not_publication_and_failure_remains_distinct(self):
        self.record()
        for state, stage in [('success','pushed'),('running','building'),('failed','failed')]:
            with patch.object(p, 'api', return_value=[{'sha':self.sha,'ref':'main','status':state,'web_url':'https://git.example.invalid/pipeline/1'}]) as api:
                result = p.status(self.source, check=True)
            self.assertEqual(result['stage'], stage)
            self.assertEqual(result['pipeline_status'], state)
            # The pipeline is looked up by this revision (later optional lookups may follow).
            self.assertTrue(any(self.sha in call[0][2] for call in api.call_args_list))
            self.assertNotIn('Private synthetic draft', str(api.call_args))

    def test_gitlab_matching_environment_deployment_can_verify_revision(self):
        p.record(self.source, self.plan, self.sha, 'pages')
        for revision, environment, expected in [(self.sha,'pages','published'),('b'*40,'pages','pushed'),(self.sha,'other','pushed')]:
            with patch.object(p, 'api', side_effect=[[],[{'status':'success','sha':revision,'environment':{'name':environment}}]]):
                result = p.status(self.source, check=True)
            self.assertEqual(result['stage'], expected)

    def test_github_checks_latest_deployment_not_historical_success(self):
        self.record(provider='github', project_url='https://github.com/example/docs')
        calls = [ {'workflow_runs':[{'head_sha':self.sha,'head_branch':'main','conclusion':'success'}]},
                  [{'id':123,'sha':self.sha,'environment':'github-pages'}], [{'state':'success','environment_url':'https://example.github.io/docs'}] ]
        with patch.object(p, 'api', side_effect=calls):
            self.assertEqual(p.status(self.source, check=True)['stage'], 'published')
        calls[1][0]['sha'] = 'b'*40
        with patch.object(p, 'api', side_effect=[*calls, {'status':'built','commit':'b'*40}]):
            result = p.status(self.source, check=True)
            self.assertEqual(result['stage'], 'pushed')
            self.assertEqual(result['deployed_revision'], 'b'*40)

    def test_status_failure_does_not_reuse_old_published_claim(self):
        value = self.record(); value.update(stage='published',deployed_revision=self.sha)
        p.store(self.source, value)
        with patch.object(p, 'api', side_effect=Error('No existing login')):
            result = p.status(self.source, check=True)
        self.assertEqual(result['stage'],'pushed')
        self.assertNotIn('deployed_revision',result)
        self.assertIn('No existing login',result['check_error'])

    def test_newer_push_wins_during_status_request(self):
        self.record()
        def query(*_):
            p.record(self.source,self.plan,'b'*40)
            return []
        with patch.object(p,'api',side_effect=query):
            self.assertEqual(p.status(self.source,check=True)['revision'],'b'*40)

    def test_failed_build_request_survives_reopen_until_pipeline_is_observed(self):
        self.record(deployment_error='The build tool is not installed.')
        self.assertEqual(p.status(self.source)['deployment_error'], 'The build tool is not installed.')
        with patch.object(p, 'api', side_effect=Error('No existing login')):
            self.assertIn('deployment_error', p.status(self.source, check=True))
        with patch.object(p, 'api', return_value=[{'sha': self.sha, 'ref': 'main', 'status': 'running'}]):
            result = p.status(self.source, check=True)
        self.assertEqual(result['stage'], 'building')
        self.assertNotIn('deployment_error', result)

    def test_failed_refresh_does_not_reuse_old_build_progress(self):
        value = self.record()
        value.update(stage='building', pipeline_id=3, build_step='slides')
        p.store(self.source, value)
        with patch.object(p, 'api', side_effect=Error('No existing login')):
            result = p.status(self.source, check=True)
        self.assertNotIn('pipeline_id', result)
        self.assertNotIn('build_step', result)

    def test_unsafe_links_and_corrupt_receipts_fail_closed(self):
        self.assertIsNone(p.safe_url('javascript:alert(1)'))
        self.assertIsNone(p.safe_url('https://user:password@example.invalid/'))
        with self.assertRaises(Error): p.record(self.source,self.plan,'not a commit')
        self.record(project_url='https://user:secret@example.invalid/team/docs')
        with patch.object(p,'api',side_effect=AssertionError('No network')):
            self.assertEqual(p.status(self.source,check=True)['stage'],'pushed')

    def test_pipeline_failure_is_retained_when_deployment_lookup_is_unavailable(self):
        self.record(provider='github', project_url='https://github.com/example/docs')
        with patch.object(p, 'api', side_effect=[{'workflow_runs':[{'head_sha':self.sha,'head_branch':'main','conclusion':'failure'}]}, Error('Deployment read denied')]):
            result = p.status(self.source,check=True)
        self.assertEqual(result['stage'],'failed')
        self.assertIn('denied',result['check_error'])


if __name__ == '__main__': unittest.main()
