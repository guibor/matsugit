import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit import repositories, targets
from matsugit.core import Error, git


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.env = patch.dict(os.environ, {'MATSUGIT_CONFIG':str(self.root/'config.json'), 'MATSUGIT_REPOSITORIES_DIR':str(self.root/'repos')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.github = {'full_name':'team/docs', 'html_url':'https://github.example/team/docs',
                       'clone_url':'https://github.example/team/docs.git', 'default_branch':'main', 'permissions':{'push':True}}
        self.gitlab = {'path_with_namespace':'group/sub/docs', 'web_url':'https://gitlab.example/group/sub/docs',
                       'http_url_to_repo':'https://gitlab.example/group/sub/docs.git', 'default_branch':'main'}

    def test_discover_existing_auth_cli_and_bounded_pagination(self):
        for provider, item in [('github', self.github), ('gitlab', self.gitlab)]:
            with patch.object(repositories, 'command', return_value=json.dumps([item])) as cli:
                result = repositories.discover(provider, provider+'.example', 2)
                self.assertEqual(result['repositories'][0]['branch'], 'main')
                self.assertIn('page=2', cli.call_args.args[0][-1])
                self.assertIn('--hostname', cli.call_args.args[0])
                self.assertNotIn('auth', cli.call_args.args[0])

    def fake_clone(self, args):
        self.assertEqual(args[:2], ['git', 'clone'])
        stage = Path(args[-1]); stage.mkdir()
        git(stage, 'init', '-b', 'main')
        git(stage, 'config', 'user.name', 'Test'); git(stage, 'config', 'user.email', 'test@example.invalid')
        (stage / 'README.md').write_text('Synthetic repository')
        git(stage, 'add', '.'); git(stage, 'commit', '-m', 'Initial')
        git(stage, 'remote', 'add', 'origin', args[-2])
        return ''

    def test_connect_clones_once_without_push_or_changing_default(self):
        targets.save({'theme':'personal', 'default_publish_target':'existing'})
        with patch.object(repositories, 'api', return_value=self.github), patch.object(repositories, 'command', side_effect=self.fake_clone) as clone:
            first = repositories.connect('github', 'github.example', 'team/docs')
            second = repositories.connect('github', 'github.example', 'team/docs')
            self.assertEqual(first['target'], second['target'])
            self.assertEqual(clone.call_count, 1)
        profile = targets.resolve(first['target'])
        self.assertEqual(profile['build'], 'ci')
        self.assertEqual(profile['expected_remote'], self.github['clone_url'])
        self.assertEqual(targets.settings()['default_publish_target'], 'existing')
        self.assertFalse((Path(first['repo']) / '.github').exists())

    def test_nested_gitlab_identifier_is_encoded(self):
        with patch.object(repositories, 'api', return_value=self.gitlab) as api, patch.object(repositories, 'command', side_effect=self.fake_clone):
            repositories.connect('gitlab', 'gitlab.example', 'group/sub/docs')
            self.assertEqual(api.call_args.args[-1], 'projects/group%2Fsub%2Fdocs')

    def test_invalid_destinations_never_clone(self):
        for item in (dict(self.github, archived=True), dict(self.github, default_branch=None),
                     dict(self.github, clone_url='https://token@github.example/team/docs.git'),
                     dict(self.github, clone_url='https://other.example/team/docs.git'),
                     dict(self.github, permissions={'push':False})):
            with patch.object(repositories, 'api', return_value=item), patch.object(repositories, 'command') as clone:
                with self.assertRaises(Error): repositories.connect('github', 'github.example', 'team/docs')
                clone.assert_not_called()
        for host, name in [('https://github.com', 'team/repo'), ('github.com','../bad'), ('github.com','https://evil/repo')]:
            with self.assertRaises(Error): repositories.validate('github', host, name)


if __name__ == '__main__': unittest.main()
