"""运行：python3 -B -m unittest -v test_web.py。测试使用临时目录和假 Key。"""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import web
from jev import AnswerError


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        keyfile = patch.object(web, 'KEY_FILE', Path(self.temp.name) / 'keys' / 'api-key')
        keyfile.start()
        self.addCleanup(keyfile.stop)
        env = patch.dict(os.environ, {'TYPESAFE_API_KEY': ''})
        env.start()
        self.addCleanup(env.stop)
        self.server = web.make_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, data=None, headers=None):
        supplied = {'Content-Type': 'application/json', 'X-Jev-Token': self.server.token}
        supplied.update(headers or {})
        request = urllib.request.Request(self.base + path, headers=supplied,
            data=None if data is None else json.dumps(data).encode())
        try:
            response = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read().decode()

    def test_persistence_and_no_secret_in_responses(self):
        secret = 'fake-test-key-not-a-credential'
        self.assertEqual(self.request('/api/key', {'key': secret})[0], 200)
        self.assertEqual(web.KEY_FILE.read_text(), secret)
        if os.name != 'nt':
            self.assertEqual(web.KEY_FILE.stat().st_mode & 0o777, 0o600)
        self.stop_server()
        self.server = web.make_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        with patch.object(web, 'ask', return_value=0.75) as ask:
            status, body = self.request('/api/ask', {'text': '文本', 'question': '是否？'})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {'yes': 0.75, 'no': 0.25})
            ask.assert_called_once_with('文本', '是否？', secret)
        for path in ['/', '/api/status']:
            self.assertNotIn(secret, self.request(path)[1])
        self.assertEqual(self.request('/api/key/delete', {})[0], 200)
        self.assertFalse(web.KEY_FILE.exists())

    def test_cross_site_and_host_rejected(self):
        for headers in [{'X-Jev-Token': 'wrong'}, {'Origin': 'https://evil.example'}, {'Host': 'evil.example'}]:
            self.assertEqual(self.request('/api/key', {'key': 'fake-key'}, headers)[0], 403)
        self.assertFalse(web.KEY_FILE.exists())
        self.assertEqual(self.request('/', headers={'Host': 'evil.example'})[0], 403)

    def test_validation_and_safe_errors(self):
        self.assertEqual(self.request('/api/ask', {'text': 'text', 'question': 'yes?'})[0], 400)
        web.save_key('fake-key')
        with patch.object(web, 'ask') as ask:
            self.assertEqual(self.request('/api/ask', {'text': ' ', 'question': 'yes?'})[0], 400)
            ask.assert_not_called()
        error = urllib.error.HTTPError('https://example.invalid', 401, 'fake-key', {}, None)
        with patch.object(web, 'ask', side_effect=error):
            status, body = self.request('/api/ask', {'text': 'text', 'question': 'yes?'})
            self.assertEqual(status, 502)
            self.assertNotIn('fake-key', body)
        self.assertEqual(self.request('/api/key', {'key': 'key\nheader'})[0], 400)
        self.assertEqual(self.request('/api/key', {'key': 'fake'}, {'Content-Type': 'text/plain'})[0], 415)

    def test_oversized_request_rejected_before_body_is_read(self):
        # 只发送声明长度的请求头，验证服务端在读取大请求体前拒绝。
        # 避免客户端仍在发送请求体时连接关闭产生 BrokenPipe 竞态。
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        self.addCleanup(connection.close)
        connection.putrequest('POST', '/api/ask')
        connection.putheader('Content-Type', 'application/json')
        connection.putheader('X-Jev-Token', self.server.token)
        connection.putheader('Content-Length', '256001')
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 413)
        self.assertIn('256 KB', json.loads(response.read())['error'])

    def test_choice_and_score_routes(self):
        web.save_key('fake-key')
        cases = [
            ('choice', {'账务': '退款', '技术': '故障'},
             {'type': 'choice', 'choice': '账务', 'probabilities': {'账务': 0.9, '技术': 0.1}, 'confidence': 0.7}),
            ('score', ['轻微', '中等', '严重'],
             {'type': 'score', 'score': 1.4, 'probabilities': {'0': 0.1, '1': 0.4, '2': 0.5},
              'confidence': 0.3, 'legend': {'0': '轻微', '1': '中等', '2': '严重'}}),
        ]
        for kind, criteria, answer in cases:
            with self.subTest(kind=kind), patch.object(web, 'evaluate', return_value=answer) as evaluate:
                status, body = self.request('/api/ask', {'text': '文本', 'question': '判断问题', 'type': kind, 'criteria': criteria})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body), answer)
                evaluate.assert_called_once_with('文本', '判断问题', 'fake-key', kind, criteria)

    def test_invalid_criteria_never_calls_service(self):
        web.save_key('fake-key')
        cases = [
            ('other', None), ('choice', None), ('choice', ['a', 'b']),
            ('choice', {'a': None}), ('choice', {'a': None, ' a ': None}),
            ('choice', {'a': [], 'b': None}), ('choice', {str(i): None for i in range(256)}),
            ('score', {}), ('score', ['a']), ('score', ['a', ' ']),
            ('score', ['a', 'a']), ('score', list(map(str, range(11)))),
        ]
        with patch.object(web, 'evaluate') as evaluate, patch.object(web, 'ask') as ask:
            for kind, criteria in cases:
                with self.subTest(kind=kind, criteria=criteria):
                    self.assertEqual(self.request('/api/ask', {'text': '文本', 'question': '问题', 'type': kind, 'criteria': criteria})[0], 400)
            evaluate.assert_not_called()
            ask.assert_not_called()

    def test_invalid_remote_answer_is_safe_gateway_error(self):
        web.save_key('fake-key')
        with patch.object(web, 'evaluate', side_effect=AnswerError('secret-like-content')):
            status, body = self.request('/api/ask', {'text': '文本', 'question': '问题', 'type': 'score', 'criteria': ['低', '高']})
            self.assertEqual(status, 502)
            self.assertNotIn('secret-like-content', body)


if __name__ == '__main__':
    unittest.main()
