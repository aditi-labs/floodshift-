"""Atomic local JSON checkpoints in SQLite; no extra package or cloud dependency."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


class SessionError(RuntimeError):
    """Session could not be safely loaded or committed."""


class SessionConflict(SessionError):
    """Another service committed; reopen instead of overwriting newer state."""


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return sha256(encode(value).encode()).hexdigest()


class SessionStore:
    def __init__(self, path):
        self.path = Path(path)
        self.revision = None
        # The gateway supplies a trusted local path, not a filename from model input.
        if not self.path.parent.is_dir():
            raise SessionError('session_directory_missing')
        try:
            with closing(sqlite3.connect(self.path)) as connection:
                connection.execute('CREATE TABLE IF NOT EXISTS world_session '
                    '(id INTEGER PRIMARY KEY CHECK (id=1), revision INTEGER NOT NULL, '
                    'payload TEXT NOT NULL, digest TEXT NOT NULL)')
                connection.commit()
        except sqlite3.Error as error:
            raise SessionError('session_unavailable') from error

    def read(self):
        try:
            with closing(sqlite3.connect(self.path)) as connection:
                row = connection.execute('SELECT revision, payload, digest FROM world_session WHERE id=1').fetchone()
            if row is None:
                return None
            revision, encoded, digest = row
            if sha256(encoded.encode()).hexdigest() != digest:
                raise SessionError('session_checksum_mismatch')
            payload = json.loads(encoded)
            if not isinstance(payload, dict):
                raise SessionError('invalid_session_payload')
            self.revision = revision
            return payload
        except (sqlite3.Error, ValueError, TypeError) as error:
            raise SessionError('session_unreadable') from error

    def save(self, payload):
        encoded = encode(payload)
        digest = sha256(encoded.encode()).hexdigest()
        try:
            with closing(sqlite3.connect(self.path, timeout=5)) as connection:
                # One durable transaction: readers never observe half a checkpoint.
                connection.execute('PRAGMA synchronous=FULL')
                connection.execute('BEGIN IMMEDIATE')
                row = connection.execute('SELECT revision FROM world_session WHERE id=1').fetchone()
                current = row[0] if row else None
                if current != self.revision:
                    raise SessionConflict('session_conflict')
                revision = 0 if current is None else current + 1
                connection.execute('INSERT OR REPLACE INTO world_session VALUES (1, ?, ?, ?)',
                                   (revision, encoded, digest))
                connection.commit()
                self.revision = revision
        except sqlite3.Error as error:
            raise SessionError('session_write_failed') from error
