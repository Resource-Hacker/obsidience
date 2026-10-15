"""Discord's private ingress ledger; never an Executive Chat projection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

AGENT_REF = 'Agents/Discord/Discord'
MAX_TEXT = 8_000


def snowflake(value: str) -> str:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or not 5 <= len(value) <= 24:
        raise ValueError('Discord identity must be an exact snowflake string')
    return value


@dataclass(frozen=True)
class DiscordTurn:
    store: 'DiscordStore'
    conversation_id: str
    turn_id: str
    text: str
    metadata: dict

    @property
    def agent_ref(self):
        return AGENT_REF

    @property
    def user_id(self):
        return 'discord:' + ':'.join(self.metadata[key] for key in ('guild_id', 'channel_id', 'member_id'))

    @property
    def agent_name(self):
        return 'discord'

    def validate(self):
        row = self.store.turn(self.turn_id)
        if (row is None or row['state'] != 'running' or row['conversation_id'] != self.conversation_id
                or row['text'] != self.text or self.store.metadata(row) != self.metadata):
            raise ValueError('Discord conversation requires its exact durable admitted member turn')
        return row

    def history(self):
        return self.store.history(self.conversation_id, self.turn_id)

    def previous_request(self):
        return next((row['text'] for row in reversed(self.history()) if row['role'] == 'user'), '')[:200]

    def anchor(self):
        row = self.store.db.execute('SELECT anchor FROM conversations WHERE id=?', (self.conversation_id,)).fetchone()
        return row[0] if row else None


class DiscordStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.db = None

    def start(self):
        if self.db is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, cached_statements=0)
        self.path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS conversations(
                id TEXT PRIMARY KEY, agent_ref TEXT NOT NULL, guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL, member_id TEXT NOT NULL, anchor TEXT,
                UNIQUE(agent_ref,guild_id,channel_id,member_id));
            CREATE TABLE IF NOT EXISTS turns(
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
                request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, source TEXT NOT NULL,
                display_name TEXT NOT NULL, text TEXT NOT NULL, memory_writeback INTEGER NOT NULL,
                state TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL,
                UNIQUE(conversation_id,request_id));
        ''')
        # A prior process may have dispatched Tools. Its requests never become
        # retryable merely because their transport or the Harness restarted.
        self.db.execute("UPDATE turns SET state='interrupted', result=? WHERE state IN ('admitted','running')",
                        (json.dumps({'status': 'interrupted', 'reply': '', 'must_not_replay': True}),))

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def admit(self, text, *, guild_id, channel_id, member_id, request_id, source='text',
              memory_writeback=True, display_name=''):
        for value in (guild_id, channel_id, member_id):
            snowflake(value)
        if (not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT
                or any(ord(char) < 32 and char not in '\n\t' for char in text)):
            raise ValueError('Discord request must contain 1–8000 characters')
        if (not isinstance(request_id, str) or not request_id or len(request_id) > 128
                or any(ord(char) < 32 for char in request_id)):
            raise ValueError('Discord request requires a bounded stable ingress id')
        if (source not in {'text', 'voice'} or type(memory_writeback) is not bool
                or not isinstance(display_name, str) or len(display_name) > 100
                or any(ord(char) < 32 for char in display_name)):
            raise ValueError('Discord ingress metadata is invalid')
        scope = [AGENT_REF, guild_id, channel_id, member_id]
        conversation = 'discord-' + uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(scope)).hex
        digest = hashlib.sha256(json.dumps([text, source, memory_writeback, display_name]).encode()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('INSERT OR IGNORE INTO conversations(id,agent_ref,guild_id,channel_id,member_id) '
                            'VALUES(?,?,?,?,?)', (conversation, *scope))
            row = self.db.execute('SELECT * FROM turns WHERE conversation_id=? AND request_id=?',
                                  (conversation, request_id)).fetchone()
            duplicate = row is not None
            if row is not None and row['fingerprint'] != digest:
                raise ValueError('Discord ingress id was reused with different request content')
            if row is None:
                identifier = uuid.uuid4().hex
                self.db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?,?,?,?)', (
                    identifier, conversation, request_id, digest, source, display_name, text,
                    int(memory_writeback), 'admitted', None, datetime.now().astimezone().isoformat()))
                row = self.turn(identifier)
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        return self.binding(row), duplicate

    def turn(self, identifier):
        return self.db.execute('SELECT * FROM turns WHERE id=?', (identifier,)).fetchone()

    def metadata(self, row):
        scope = self.db.execute('SELECT guild_id,channel_id,member_id FROM conversations WHERE id=?',
                                (row['conversation_id'],)).fetchone()
        return {**dict(scope), **{key: row[key] for key in ('request_id', 'source', 'display_name')}}

    def binding(self, row):
        return DiscordTurn(self, row['conversation_id'], row['id'], row['text'], self.metadata(row))

    def begin(self, turn):
        changed = self.db.execute("UPDATE turns SET state='running' WHERE id=? AND state='admitted'",
                                  (turn.turn_id,)).rowcount
        if changed != 1:
            raise ValueError('Discord turn was already started; it cannot be replayed')

    def finish(self, turn, result):
        self.db.execute("UPDATE turns SET state=?,result=? WHERE id=? AND state IN ('admitted','running')",
                        (result['status'], json.dumps(result), turn.turn_id))

    def result(self, turn):
        row = self.turn(turn.turn_id)
        result = json.loads(row['result']) if row['result'] else {'status': row['state'], 'reply': ''}
        return {**result, 'conversation_id': turn.conversation_id, 'turn_id': turn.turn_id}

    def history(self, conversation, before_turn):
        current = self.turn(before_turn)
        anchor = self.binding(current).anchor()
        rows = self.db.execute("SELECT rowid,* FROM turns WHERE conversation_id=? AND rowid < "
                               '(SELECT rowid FROM turns WHERE id=?) AND rowid >= '
                               'COALESCE((SELECT rowid FROM turns WHERE id=?),0) ORDER BY rowid',
                               (conversation, before_turn, anchor)).fetchall()
        started = not anchor
        output = []
        for row in rows:
            if row['id'] == anchor:
                started = True
            if not started:
                continue
            result = json.loads(row['result']) if row['result'] else {}
            # Only settled exchanges seed a missing native log. Uncertain effects
            # stay in the native audit log and are never reconstructed as success.
            if row['state'] != 'completed' or not result.get('reply'):
                continue
            output += [{'id': row['id'], 'role': 'user', 'text': row['text']},
                       {'id': row['id'] + '-reply', 'role': 'assistant', 'text': result['reply'],
                        'reply_to': row['id']}]
        return output

    def completed(self):
        return self.db.execute("SELECT * FROM turns WHERE state='completed' ORDER BY rowid").fetchall()

    def recovery(self):
        return [self.binding(row) for row in self.db.execute("SELECT * FROM turns WHERE state='interrupted'")]

    def rebase(self, turn, messages):
        """Keep a bounded native provider window, leaving the ADK audit log intact.

        The binding explicitly warns that omitted dialogue may not yet be in
        Hindsight. Discord never updates the Executive's window/retention state.
        """
        owners = [n for n, row in enumerate(messages) if row.get('source', {}).get('kind') == 'user']
        estimate = lambda rows: sum(len(json.dumps(row, ensure_ascii=False)) for row in rows
                                    if row.get('role') != 'system') // 4
        if len(owners) <= 6 and estimate(messages) <= 4_000:
            return
        if len(owners) < 3:
            return  # Always preserve at least two complete exchanges.
        keep = len(owners) - 2
        while keep > 0 and len(owners) - keep < 3 and estimate(messages[owners[keep - 1]:]) <= 2_000:
            keep -= 1
        anchor = messages[owners[keep]].get('id')
        if anchor and self.turn(anchor) is not None:
            self.db.execute('UPDATE conversations SET anchor=? WHERE id=?', (anchor, turn.conversation_id))
