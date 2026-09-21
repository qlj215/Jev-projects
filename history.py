"""本机历史记录；仅在用户选择保存时写入，数据库位于项目目录之外。"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3


HISTORY_FILE = Path.home() / '.local' / 'share' / 'jev-local' / 'history.sqlite3'
PAGE_SIZE = 20


@contextmanager
def database(create=False):
    if not create and not HISTORY_FILE.exists():
        yield None
        return
    if create:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(HISTORY_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
    connection = sqlite3.connect(HISTORY_FILE, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA secure_delete = ON')
        with connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS history (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL,
                kind TEXT NOT NULL, text TEXT NOT NULL, question TEXT NOT NULL,
                criteria TEXT NOT NULL, answer TEXT NOT NULL
            )''')
            yield connection
    finally:
        connection.close()


def save(text, question, kind, criteria, answer):
    record_id = secrets.token_urlsafe(18)
    with database(create=True) as connection:
        connection.execute(
            'INSERT INTO history (id, created_at, kind, text, question, criteria, answer) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (record_id, datetime.now(timezone.utc).isoformat(), kind, text, question,
             json.dumps(criteria, ensure_ascii=False), json.dumps(answer, ensure_ascii=False)),
        )
    return record_id


def list_records(offset=0):
    with database() as connection:
        if connection is None:
            return {'items': [], 'total': 0, 'has_more': False}
        total = connection.execute('SELECT COUNT(*) FROM history').fetchone()[0]
        rows = connection.execute(
            'SELECT id, created_at, kind AS type, substr(text, 1, 120) AS text, '
            'substr(question, 1, 120) AS question FROM history ORDER BY sequence DESC LIMIT ? OFFSET ?',
            (PAGE_SIZE, offset),
        ).fetchall()
        return {'items': [dict(row) for row in rows], 'total': total, 'has_more': offset + len(rows) < total}


def get(record_id):
    with database() as connection:
        if connection is None:
            return None
        row = connection.execute(
            'SELECT id, created_at, kind AS type, text, question, criteria, answer FROM history WHERE id = ?',
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record['criteria'] = json.loads(record['criteria'])
        record['answer'] = json.loads(record['answer'])
        return record


def delete(record_id):
    with database() as connection:
        return 0 if connection is None else connection.execute('DELETE FROM history WHERE id = ?', (record_id,)).rowcount


def clear():
    with database() as connection:
        return 0 if connection is None else connection.execute('DELETE FROM history').rowcount
