import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from get3w_bench.proxy import extract_usage, server


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    captured = []
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            captured.append((self.path, dict(self.headers), body))
            if body.get('stream'):
                data = b'data: {"choices": [{"delta": {"content": "hi"}}]}\n\ndata: {"usage": {"prompt_tokens": 3, "completion_tokens": 2}}\n\ndata: [DONE]\n\n'
                content_type = 'text/event-stream'
            else:
                data = b'{"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}'
                content_type = 'application/json'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('BENCH_TEST_PROVIDER', 'provider-secret')
    config = dict(model=dict(id='test', endpoint=f'http://127.0.0.1:{upstream.server_port}/v1', api_format='chat_completions', api_key_env='BENCH_TEST_PROVIDER', parameters={'temperature': 0}), budget=dict(timeout_sec=2, max_requests=2, max_output_tokens=10))
    instance = server(config, tmp_path, token='disposable')
    worker = threading.Thread(target=instance.serve_forever, daemon=True)
    worker.start()
    with httpx.Client(base_url=f'http://127.0.0.1:{instance.server_port}', headers={'Authorization': 'Bearer disposable'}, trust_env=False) as client:
        yield client, captured, tmp_path, instance
    instance.shutdown()
    upstream.shutdown()
    instance.server_close()
    upstream.server_close()
    worker.join()
    thread.join()


def test_streaming_usage_and_budgets(gateway):
    client, captured, directory, instance = gateway
    body = dict(model='test', messages=[], temperature=0)
    assert client.post('/v1/chat/completions', json={**body, 'stream': True}).status_code == 200
    assert client.post('/chat/completions', json=body).status_code == 200
    assert client.post('/v1/chat/completions', json=body).status_code == 400
    summary = json.loads((directory/'summary.json').read_text())
    assert summary['usage_complete'] and summary['output_tokens'] == 4
    assert summary['accepted_requests'] == summary['recorded_requests'] == 2
    assert captured[0][2]['stream_options']['include_usage']
    assert captured[0][2]['max_tokens'] == 10
    assert captured[0][1]['Authorization'] == 'Bearer provider-secret'
    assert 'provider-secret' not in (directory/'transactions.jsonl').read_text()
    assert captured[0][0] == '/v1/chat/completions'


@pytest.mark.parametrize('body', [{'model': 'other', 'temperature': 0}, {'model': 'test', 'temperature': 1}, [], {'model': 'test', 'temperature': 0, 'max_tokens': 11}, {'model': 'test', 'temperature': 0, 'max_tokens': True}])
def test_rejects_before_provider(gateway, body):
    client, captured, _, _ = gateway
    assert client.post('/v1/chat/completions', json=body).status_code == 400
    assert not captured


def test_auth_path_and_invalid_body(gateway):
    client, captured, _, _ = gateway
    assert client.post('/v1/chat/completions', headers={'Authorization': 'Bearer bad'}, json={}).status_code == 401
    assert client.post('/v1/chat/completions?redirect=x', json={}).status_code == 404
    assert client.post('/v1/chat/completions', content=b'bad').status_code == 400
    assert not captured


@pytest.mark.parametrize('raw', [b'{}', b'{"usage":{"output_tokens":1}}', b'{"usage":{"input_tokens":1,"output_tokens":-1}}', b'data: [DONE]\n'])
def test_incomplete_usage(raw):
    assert extract_usage(raw) is None
