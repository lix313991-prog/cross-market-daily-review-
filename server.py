#!/usr/bin/env python3
"""Minimal local backend proxy for the cross-market dashboard.

Uses only Python's standard library. The upstream quote provider is configurable.
This starter deliberately does not claim any quote is live until the upstream returns it.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json, os, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "10000"))
UPSTREAM = os.environ.get('QUOTE_API_BASE', 'https://api.ashareapi.com/v1/quote')
TIMEOUT = float(os.environ.get('QUOTE_TIMEOUT', '12'))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/health':
            return self.send_json(200, {'ok': True, 'service': 'cross-market-dashboard-proxy', 'upstream_configured': bool(UPSTREAM)})
        if parsed.path == '/api/quote':
            code = parse_qs(parsed.query).get('code', [''])[0].strip()
            if not code or len(code) > 40 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in code):
                return self.send_json(400, {'error': '请提供有效代码，例如 sh000688、hk00700、usAAPL。'})
            url = UPSTREAM + ('&' if '?' in UPSTREAM else '?') + urlencode({'code': code})
            req = Request(url, headers={'User-Agent': 'CrossMarketDashboard/0.1', 'Accept': 'application/json'})
            try:
                with urlopen(req, timeout=TIMEOUT) as response:
                    raw = response.read()
                    try:
                        data = json.loads(raw.decode('utf-8'))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        return self.send_json(502, {'error': '上游返回内容不是有效 JSON。', 'upstream_status': response.status})
                    return self.send_json(200, {'ok': True, 'code': code, 'source': UPSTREAM, 'fetched_at_utc': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(), 'data': data})
            except HTTPError as e:
                detail = e.read(800).decode('utf-8', errors='replace')
                return self.send_json(502, {'error': '上游行情接口返回错误。', 'upstream_status': e.code, 'detail': detail})
            except (URLError, TimeoutError, OSError) as e:
                return self.send_json(502, {'error': '无法连接上游行情接口。', 'detail': str(e)})
        return super().do_GET()

    def log_message(self, fmt, *args):
        # Avoid logging full URLs/query strings; only log request path.
        path = urlparse(self.path).path
        print(f'{self.address_string()} {self.command} {path}')

if __name__ == '__main__':
    print(f'Dashboard: http://{HOST}:{PORT}')
    print('API health: /api/health | Quote: /api/quote?code=sh000688')
    print('Note: upstream coverage, delays, and licensing must be verified before production use.')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
