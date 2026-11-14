"""Private, bounded source checkpoints. Never writes the document itself."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import time

MAX_SOURCE = 2 * 1024 * 1024
REASONS = {'opened', 'before-save', 'saved', 'external', 'before-restore', 'agent-edit', 'draft'}


class History:
    def __init__(self, directory, *, per_document=64, max_events=2048, max_bytes=128 * 1024 * 1024):
        self.directory = Path(directory).absolute()
        self.per_document, self.max_events, self.max_bytes = per_document, max_events, max_bytes

    @staticmethod
    def private(path, *, directory=False):
        info = path.lstat()
        kind = stat.S_ISDIR if directory else stat.S_ISREG
        if not kind(info.st_mode) or (hasattr(os, 'getuid') and
                (info.st_uid != os.getuid() or info.st_mode & 0o077)):
            raise ValueError('History storage must be private and owned by your user')

    @contextmanager
    def database(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.private(self.directory, directory=True)
        file = self.directory / 'history.sqlite3'
        # SQLite creates journals beside the database. Refuse redirected files.
        for suffix in ('', '-journal', '-wal', '-shm'):
            target = Path(str(file) + suffix)
            if target.exists() or target.is_symlink():
                self.private(target)
        if not file.exists():
            try:
                fd = os.open(file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            except FileExistsError:
                self.private(file)
        db = sqlite3.connect(file, timeout=10)
        try:
            db.execute('PRAGMA auto_vacuum=FULL')
            page_size = db.execute('PRAGMA page_size').fetchone()[0]
            db.execute(f'PRAGMA max_page_count={160 * 1024 * 1024 // page_size}')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('History was written by a newer workspace; retained unchanged')
            db.execute('CREATE TABLE IF NOT EXISTS blobs (digest TEXT PRIMARY KEY, text TEXT NOT NULL, size INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, digest TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS owner_events ON events(owner, id)')
            db.execute('PRAGMA user_version=1')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def owner(value):
        if not isinstance(value, str) or not value or len(value) > 4096 or '\0' in value:
            raise ValueError('Invalid history document identity')
        return value

    def record(self, owner, text, reason):
        owner = self.owner(owner)
        if reason not in REASONS or not isinstance(text, str) or '\0' in text:
            raise ValueError('Invalid source checkpoint')
        data = text.encode('utf-8')
        if len(data) > MAX_SOURCE:
            raise ValueError('Source checkpoint exceeds 2 MiB')
        digest = sha256(data).hexdigest()
        with self.database() as db:
            last = db.execute('SELECT id, digest, reason FROM events WHERE owner=? ORDER BY id DESC LIMIT 1', (owner,)).fetchone()
            if last and last[1:] == (digest, reason):
                return {'id': str(last[0]), 'digest': digest}
            db.execute('INSERT OR IGNORE INTO blobs VALUES (?, ?, ?)', (digest, text, len(data)))
            identifier = db.execute('INSERT INTO events(owner,digest,reason,created) VALUES (?,?,?,?)',
                                    (owner, digest, reason, time.time())).lastrowid
            # Keep the latest event of each kind for every document. Prune only
            # older history, under the same transaction as the new checkpoint.
            protected = {r[0] for r in db.execute('SELECT MAX(id) FROM events GROUP BY owner,reason')}
            rows = db.execute('SELECT id,owner FROM events ORDER BY id').fetchall()
            counts = dict(db.execute('SELECT owner,COUNT(*) FROM events GROUP BY owner'))
            total = len(rows)
            size = db.execute('SELECT COALESCE(SUM(size),0) FROM blobs').fetchone()[0]
            for key, document in rows:
                if counts[document] <= self.per_document and total <= self.max_events and size <= self.max_bytes:
                    continue
                if key in protected:
                    continue
                db.execute('DELETE FROM events WHERE id=?', (key,))
                db.execute('DELETE FROM blobs WHERE digest NOT IN (SELECT digest FROM events)')
                counts[document] -= 1
                total -= 1
                size = db.execute('SELECT COALESCE(SUM(size),0) FROM blobs').fetchone()[0]
            if size > self.max_bytes or total > self.max_events or max(counts.values()) > self.per_document:
                raise ValueError('History storage is full; existing checkpoints retained. Free space or choose another private history directory before retrying.')
            return {'id': str(identifier), 'digest': digest}

    def list(self, owner):
        with self.database() as db:
            rows = db.execute('SELECT id,digest,reason,created FROM events WHERE owner=? ORDER BY id DESC LIMIT ?',
                              (self.owner(owner), self.per_document)).fetchall()
        return {'items': [dict(zip(('id', 'digest', 'reason', 'created'), (str(a), b, c, d))) for a, b, c, d in rows],
                'source_only': True}

    def read(self, owner, identifier):
        if not isinstance(identifier, str) or not identifier.isdecimal() or len(identifier) > 18:
            raise ValueError('Invalid history checkpoint')
        with self.database() as db:
            row = db.execute('SELECT text,digest,reason,created FROM events JOIN blobs USING(digest) WHERE id=? AND owner=?',
                             (int(identifier), self.owner(owner))).fetchone()
        if not row:
            raise ValueError('Checkpoint no longer available for this document; refresh History')
        if sha256(row[0].encode('utf-8')).hexdigest() != row[1]:
            raise ValueError('Checkpoint checksum mismatch; nothing restored')
        return dict(zip(('text', 'digest', 'reason', 'created'), row))

    def relocate(self, owner, destination):
        owner, destination = self.owner(owner), self.owner(destination)
        with self.database() as db:
            if owner == destination:
                return {'moved': False}
            if db.execute('SELECT 1 FROM events WHERE owner=? LIMIT 1', (destination,)).fetchone():
                raise ValueError('Destination already has history; previous history retained at the original identity')
            db.execute('UPDATE events SET owner=? WHERE owner=?', (destination, owner))
        return {'moved': True}


def main():
    try:
        raw = sys.stdin.buffer.read(13 * 1024 * 1024 + 1)
        if len(raw) > 13 * 1024 * 1024:
            raise ValueError('History request too large')
        request = json.loads(raw)
        history = History(request['directory'])
        operation = request['operation']
        if operation == 'record':
            result = history.record(request['owner'], request['text'], request['reason'])
        elif operation == 'list':
            result = history.list(request['owner'])
        elif operation == 'read':
            result = history.read(request['owner'], request['id'])
        elif operation == 'relocate':
            result = history.relocate(request['owner'], request['destination'])
        elif operation == 'git-list':
            from .git_history import entries, read
            items, _ = entries(request['owner'])
            result = {'items': items}
            if items:
                latest = read(request['owner'],items[0]['id'])
                result['git'] = {'revision':latest['revision'], 'source_sha256':sha256(latest['text'].encode('utf-8')).hexdigest()}
        elif operation == 'git-read':
            from .git_history import read
            result = read(request['owner'], request['id'])
        else:
            raise ValueError('Unsupported history operation')
        print(json.dumps(result))
    except (ValueError, OSError, sqlite3.Error, KeyError) as error:
        print(json.dumps({'error': str(error)}))
        sys.exit(1)


if __name__ == '__main__':
    main()
