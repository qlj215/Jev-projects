import concurrent.futures
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import history


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(history, 'HISTORY_FILE', Path(self.temp.name) / 'data' / 'history.sqlite3')
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, text='文本', kind='noul', criteria=None, answer=None):
        return history.save(text, '问题', kind, criteria, answer or {'yes': 0.8, 'no': 0.2})

    def test_empty_history_does_not_create_files(self):
        self.assertEqual(history.list_records(), {'items': [], 'total': 0, 'has_more': False})
        self.assertIsNone(history.get('absent'))
        self.assertEqual(history.delete('absent'), 0)
        self.assertEqual(history.clear(), 0)
        self.assertFalse(history.HISTORY_FILE.parent.exists())

    def test_roundtrip_all_types_permissions_and_reopen(self):
        cases = [
            ('noul', None, {'yes': 0.8, 'no': 0.2}),
            ('choice', {'甲': '选项甲', '乙': None}, {'type': 'choice', 'choice': '甲', 'probabilities': {'甲': 0.9, '乙': 0.1}, 'confidence': 0.7}),
            ('score', ['低', '中', '高'], {'type': 'score', 'score': 1.5, 'legend': {'0': '低', '1': '中', '2': '高'}, 'probabilities': {'0': 0, '1': 0.5, '2': 0.5}, 'confidence': 0.2}),
        ]
        for kind, criteria, answer in cases:
            record_id = self.save('多行\n文本 <script> & 中文', kind, criteria, answer)
            record = history.get(record_id)  # 新连接读取持久数据。
            self.assertEqual(record['text'], '多行\n文本 <script> & 中文')
            self.assertEqual(record['criteria'], criteria)
            self.assertEqual(record['answer'], answer)
            self.assertEqual(record['type'], kind)
        if os.name != 'nt':
            self.assertEqual(history.HISTORY_FILE.stat().st_mode & 0o777, 0o600)
            self.assertEqual(history.HISTORY_FILE.parent.stat().st_mode & 0o777, 0o700)

    def test_pagination_delete_clear_and_literal_ids(self):
        ids = [self.save(str(i)) for i in range(23)]
        first, second = history.list_records(), history.list_records(20)
        self.assertEqual(first['total'], 23)
        self.assertEqual([row['id'] for row in first['items']], ids[::-1][:20])
        self.assertTrue(first['has_more'])
        self.assertEqual(len(second['items']), 3)
        self.assertFalse(second['has_more'])
        self.assertEqual(history.delete("' OR 1=1 --"), 0)
        self.assertEqual(history.delete(ids[0]), 1)
        self.assertIsNone(history.get(ids[0]))
        self.assertEqual(history.clear(), 22)
        self.assertEqual(history.list_records()['total'], 0)

    def test_concurrent_saves_do_not_lose_records(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda i: self.save(str(i)), range(12)))
        self.assertEqual(len(set(ids)), 12)
        self.assertEqual(history.list_records()['total'], 12)

    def test_corrupt_database_not_silently_overwritten(self):
        history.HISTORY_FILE.parent.mkdir()
        original = b'not a sqlite database'
        history.HISTORY_FILE.write_bytes(original)
        with self.assertRaises(sqlite3.DatabaseError):
            self.save()
        self.assertEqual(history.HISTORY_FILE.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
