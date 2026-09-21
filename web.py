#!/usr/bin/env python3
"""本机 Jev 网页：python3 web.py。"""
import argparse
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error

from jev import AnswerError, QuestionError, ask, build_question, evaluate

KEY_FILE = Path.home() / '.config' / 'jev-local' / 'api-key'
PAGE = Path(__file__).with_name('index.html')
KEY_LOCK = threading.Lock()


def saved_key():
    with KEY_LOCK:
        try:
            return KEY_FILE.read_text(encoding='utf-8').strip()
        except FileNotFoundError:
            return ''


def save_key(value):
    with KEY_LOCK:
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=KEY_FILE.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                handle.write(value)
            os.replace(name, KEY_FILE)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def current_key():
    return saved_key() or os.environ.get('TYPESAFE_API_KEY', '').strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 不记录 URL、请求、密钥或响应。

    def reply(self, status, value, html=False):
        data = value.encode('utf-8') if html else json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'nonce-" + self.server.token + "'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed_host(self):
        port = self.server.server_port
        return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def do_GET(self):
        if not self.allowed_host():
            return self.reply(403, {'error': '仅允许本机访问。'})
        if self.path == '/':
            return self.reply(200, PAGE.read_text(encoding='utf-8').replace('__TOKEN__', self.server.token), html=True)
        if self.path == '/api/status':
            try:
                stored = bool(saved_key())
                return self.reply(200, {'saved': stored, 'ready': stored or bool(os.environ.get('TYPESAFE_API_KEY', '').strip())})
            except OSError:
                return self.reply(500, {'error': '无法读取本机密钥文件。'})
        self.reply(404, {'error': '页面不存在。'})

    def do_POST(self):
        port = self.server.server_port
        origin = self.headers.get('Origin')
        if (not self.allowed_host() or self.headers.get('X-Jev-Token') != self.server.token
                or origin not in (None, f'http://127.0.0.1:{port}', f'http://localhost:{port}')):
            return self.reply(403, {'error': '请求校验失败，请刷新页面。'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, {'error': '需要 JSON 请求。'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 256_000:
                return self.reply(413, {'error': '输入为空或过长（上限 256 KB）。'})
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError()
            if self.path == '/api/key':
                key = data.get('key', '')
                if not isinstance(key, str) or not key.strip() or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key.strip()):
                    return self.reply(400, {'error': '请输入有效的 API Key。'})
                save_key(key.strip())
                return self.reply(200, {'ok': True})
            if self.path == '/api/key/delete':
                with KEY_LOCK:
                    KEY_FILE.unlink(missing_ok=True)
                return self.reply(200, {'ok': True})
            if self.path != '/api/ask':
                return self.reply(404, {'error': '接口不存在。'})
            text, question = data.get('text'), data.get('question')
            if not isinstance(text, str) or not isinstance(question, str) or not text.strip() or not question.strip():
                return self.reply(400, {'error': '请填写文本和判断问题。'})
            kind = data.get('type', 'noul')
            criteria = data.get('criteria')
            typed_question = build_question(question, kind, criteria)
            key = current_key()
            if not key:
                return self.reply(400, {'error': '请先保存 API Key。'})
            if kind == 'noul':
                probability = ask(text, question, key)
                self.reply(200, {'yes': probability, 'no': 1 - probability})
            else:
                answer = evaluate(text, question, key, kind, typed_question['criteria'])
                self.reply(200, answer)
        except QuestionError as error:
            self.reply(400, {'error': str(error)})
        except AnswerError:
            self.reply(502, {'error': 'Jev 返回的判断结果格式无效，请重试。'})
        except urllib.error.HTTPError as error:
            hint = {401: 'API Key 无效，请更换后重试。', 403: '访问被拒绝，请检查账户权限。', 429: '请求过于频繁，请稍后重试。'}.get(error.code, 'Jev 服务调用失败，请稍后重试。')
            self.reply(502, {'error': hint})
        except (urllib.error.URLError, TimeoutError):
            self.reply(502, {'error': '网络连接失败或超时，请重试。'})
        except (ValueError, TypeError, KeyError):
            self.reply(400, {'error': '请求或服务响应格式无效。'})
        except OSError:
            self.reply(500, {'error': '本机文件或连接操作失败，请检查权限及网络。'})


def make_server(port):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.token = secrets.token_urlsafe(32)
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    with make_server(args.port) as server:
        print(f'Jev 网页已启动：http://127.0.0.1:{server.server_port} （Ctrl+C 停止）', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
