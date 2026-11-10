"""Local facts behind the one-button Share flow; synthetic repositories only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from matsugit import share


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class ShareStatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.remote = self.root / 'remote.git'
        git(self.root, 'init', '--bare', '--initial-branch=main', str(self.remote))
        self.repo = self.root / 'docs'; self.repo.mkdir()
        git(self.repo, 'init', '-b', 'main')
        git(self.repo, 'config', 'user.name', 'Test'); git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'remote', 'add', 'origin', 'git@git.example.invalid:team/docs.git')
        git(self.repo, 'config', 'remote.origin.pushurl', str(self.remote))
        (self.repo / 'deck.md').write_text('# Deck\n')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', 'Deck')
        git(self.repo, 'push', 'origin', 'main')
        git(self.repo, 'config', 'branch.main.remote', 'origin'); git(self.repo, 'config', 'branch.main.merge', 'refs/heads/main')
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'default_publish_target': 'docs', 'publish_targets': {
            'docs': {'repo': str(self.repo), 'build': 'ci', 'provider': 'gitlab', 'site_url': 'https://team.example.invalid/docs'},
            'rendered': {'repo': str(self.root / 'elsewhere'), 'build': 'local'}}}))
        env = patch.dict(os.environ, {'MATSUGIT_CONFIG': str(self.config)}); env.start(); self.addCleanup(env.stop)

    def test_a_loose_file_is_new_and_offers_only_projects_that_can_take_a_source(self):
        notes = self.root / 'notes'; notes.mkdir(); (notes / 'deck.md').write_text('# Deck\n')
        data = share.status(notes / 'deck.md')
        self.assertEqual(data['mode'], 'new')
        self.assertEqual(data['targets'], [{'name': 'docs', 'label': 'team/docs', 'project_url': 'https://git.example.invalid/team/docs'}])
        self.assertEqual(data['default'], 'docs')

    def test_a_tracked_file_syncs_also_through_a_link_and_an_untracked_one_does_not(self):
        data = share.status(self.repo / 'deck.md')
        self.assertEqual((data['mode'], data['target'], data['label'], data['site_url']),
                         ('sync', 'docs', 'team/docs', 'https://team.example.invalid/docs'))
        link = self.root / 'link.md'; link.symlink_to(self.repo / 'deck.md')
        self.assertEqual(share.status(link)['mode'], 'sync')
        (self.repo / 'draft.md').write_text('# Draft\n')
        self.assertEqual(share.status(self.repo / 'draft.md')['mode'], 'new')

    def test_a_push_into_a_configured_project_can_be_checked_and_another_cannot(self):
        described, environment = share.receipt_plan({'repo': str(self.repo), 'branch': 'main', 'etag': 'a' * 64})
        self.assertEqual((described['provider'], described['project_url'], described['build'], described['site_url']),
                         ('gitlab', 'https://git.example.invalid/team/docs', 'ci', 'https://team.example.invalid/docs'))
        self.assertIsNone(environment)
        other = self.root / 'notes-repo'; other.mkdir(); git(other, 'init', '-b', 'main')
        described, _ = share.receipt_plan({'repo': str(other), 'branch': 'main', 'etag': 'a' * 64})
        self.assertEqual((described['provider'], described['project_url'], described['build']), (None, None, 'git'))


if __name__ == '__main__':
    unittest.main()
