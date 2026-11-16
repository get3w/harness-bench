import json
from pathlib import Path

from get3w_bench import runner
from get3w_bench.execution import Execution
from get3w_bench.models import fingerprint, write_json
from get3w_bench.tasks import DirectorySource, lock_tasks

ROOT = Path(__file__).resolve().parents[1]


def config(tmp_path):
    source = ROOT/'suites/get3w-contract-v1'
    lock = tmp_path/'lock.json'
    tasks = DirectorySource(source).tasks()[:2]
    lock_tasks(tasks, lock, 'general')
    targets = [dict(id=b, backend=b, harness='pi', runtime_version='1.2.3', runtime_digest='abc', capabilities=['files'], tools_fingerprint='t', permissions_fingerprint='p', profile_fingerprint='p', image='example@sha256:abc', command=['worker'], url='http://bridge') for b in ('native', 'get3w')]
    return dict(schema_version=1, source={'path': str(source)}, task_lock=str(lock), model=dict(id='fixed', revision='2026-01', endpoint='http://provider/v1', api_format='chat_completions'), budget=dict(timeout_sec=1, max_requests=2, max_output_tokens=10), environment={'image_digest': 'fixed'}, gateway={'advertise_host': '127.0.0.1'}, targets=targets, grader=dict(image='grader@sha256:abc', command=['grade']), repetitions=1)


def test_runner_wires_gateway_and_preserves_planned_pairs(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    cfg['max_trials'] = 1
    calls = []
    class Target:
        def diagnose(self):
            return {'status': 'ready'}
        def execute(self, request, directory):
            calls.append(request)
            assert request['model']['endpoint'].startswith('http://127.0.0.1:')
            assert request['model']['gateway_token']
            # Controlled evidence validates orchestration only, never real model capability.
            write_json(directory/'provider-trace/summary.json', dict(usage_complete=True, accepted_requests=1, recorded_requests=1))
            return Execution('completed', identity=request['expected_identity'], trace_complete=True)
        def close(self):
            calls.append('closed')
    class Grader:
        def __init__(self, *args):
            pass
        def evaluate(self, *args):
            return dict(score=1, passed=True)
    monkeypatch.setattr(runner, 'target_for', lambda config: Target())
    monkeypatch.setattr(runner, 'DockerEvaluator', Grader)
    output = tmp_path/'run'
    rows = runner.run(cfg, output)
    assert len(rows) == 4
    assert sum(row['status'] == 'completed' for row in rows) == 1
    assert sum(row['status'] == 'blocked' for row in rows) == 3
    assert rows[0]['evidence']['usage_complete']
    assert 'closed' in calls
    saved = (output/'config.json').read_text()
    assert calls[0]['model']['gateway_token'] not in saved
    assert json.loads((output/'budget-stop.json').read_text())['completed'] == 1
    assert fingerprint(json.loads((output/'results.json').read_text())) == fingerprint(rows)


def test_blocked_runtime_does_not_call_grader(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    class Target:
        def diagnose(self):
            return dict(status='blocked', detail='not integrated')
        def close(self):
            pass
    monkeypatch.setattr(runner, 'target_for', lambda config: Target())
    rows = runner.run(cfg, tmp_path/'run')
    assert len(rows) == 4 and all(r['status'] == 'blocked' for r in rows)
