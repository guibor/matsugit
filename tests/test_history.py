from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from matsugit.history import History, MAX_SOURCE


def write_checkpoint(args):
    directory, number = args
    return History(directory).record('/deck.md', f'# Version {number}', 'saved')


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'history'
        self.history = History(self.path)

    def test_restart_dedup_and_scope(self):
        first = self.history.record('/deck.md', '# First', 'opened')
        self.assertEqual(first, self.history.record('/deck.md', '# First', 'opened'))
        self.assertEqual(History(self.path).read('/deck.md', first['id'])['text'], '# First')
        with self.assertRaisesRegex(ValueError, 'this document'):
            self.history.read('/other.md', first['id'])
        self.assertEqual(len(self.history.list('/deck.md')['items']), 1)
        self.assertEqual(self.history.list('/other.md')['items'], [])

    def test_concurrent_processes_do_not_lose_checkpoints(self):
        with ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write_checkpoint, [(self.path, n) for n in range(24)]))
        self.assertEqual(len({r['id'] for r in results}), 24)
        self.assertEqual(len(self.history.list('/deck.md')['items']), 24)

    def test_normal_record_does_not_recount_storage_for_every_event(self):
        for n in range(30):
            self.history.record('/deck.md',str(n),'saved')
        statements, connect = [], sqlite3.connect
        def traced(*args, **kwargs):
            db = connect(*args,**kwargs)
            db.set_trace_callback(statements.append)
            return db
        with patch('matsugit.history.sqlite3.connect',side_effect=traced):
            self.history.record('/deck.md','next','saved')
        self.assertEqual(sum('SUM(size)' in statement for statement in statements),1)

    def test_only_explicit_relocation_carries_history(self):
        first = self.history.record('/old.md', 'old', 'saved')
        self.assertEqual(self.history.list('/copy.md')['items'], [])
        self.history.relocate('/old.md', '/new.md')
        self.assertEqual(self.history.read('/new.md', first['id'])['text'], 'old')
        self.assertEqual(self.history.list('/old.md')['items'], [])
        self.history.record('/other.md', 'other', 'saved')
        with self.assertRaisesRegex(ValueError, 'already has history'):
            self.history.relocate('/new.md','/other.md')
        self.assertEqual(self.history.read('/new.md', first['id'])['text'], 'old')

    def test_retention_and_full_rollback(self):
        history = History(self.path, per_document=4, max_events=5, max_bytes=100)
        original = history.record('a', 'original', 'before-restore')
        for n in range(12):
            history.record('a', str(n), 'saved')
        self.assertEqual(len(history.list('a')['items']), 4)
        self.assertEqual(history.read('a', original['id'])['text'], 'original')
        before = history.list('a')
        with self.assertRaisesRegex(ValueError, 'full'):
            history.record('b', 'x'*101, 'opened')
        self.assertEqual(history.list('a'), before)
        self.assertEqual(history.list('b')['items'], [])

    def test_private_storage_oversize_and_schema(self):
        with self.assertRaisesRegex(ValueError, '2 MiB'):
            self.history.record('a', 'a'*(MAX_SOURCE+1), 'opened')
        self.history.record('a', 'safe', 'opened')
        file = self.path / 'history.sqlite3'
        if os.name != 'nt':
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(file) as db:
            db.execute('PRAGMA user_version=2')
        with self.assertRaisesRegex(ValueError, 'newer'):
            self.history.record('a', 'new', 'saved')

    @unittest.skipIf(os.name == 'nt', 'POSIX permissions')
    def test_symlink_and_public_directory_refused(self):
        self.path.mkdir(mode=0o755)
        with self.assertRaisesRegex(ValueError, 'private'):
            self.history.list('a')
        self.path.chmod(0o700)
        outside = Path(self.temp.name) / 'untouched'
        outside.write_text('private data')
        (self.path / 'history.sqlite3').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'private'):
            self.history.list('a')
        self.assertEqual(outside.read_text(), 'private data')
