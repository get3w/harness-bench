import copy
import json
import sys
from pathlib import Path

import pytest

from get3w_bench.builtin_grader import grade
from get3w_bench.compare import compare, contract_verdict, IDENTITY_FIELDS
from get3w_bench.contracts import SCENARIOS
from get3w_bench.execution import run_process, Get3WTarget
from get3w_bench.grading import validate_grade
from get3w_bench.models import fingerprint, public_config, safe_id
from get3w_bench.native_worker import command_for, terminal_status
from get3w_bench.report import report
from get3w_bench.tasks import DirectorySource, lock_tasks, verify_lock, tree_digest, contained

ROOT = Path(__file__).resolve().parents[1]


def observations(n=30, delta=0):
    result = []
    for i in range(n):
        for backend in ('native', 'get3w'):
            identity = {key: 'pinned' for key in IDENTITY_FIELDS}
            identity.update(harness='pi', suite='general', task_digest=f'task{i}')
            result.append(dict(task_id=f'task{i}', repetition=0, backend=backend, identity=identity, status='completed', evidence=dict(identity_verified=True, trace_complete=True, usage_complete=True), score=0.5 + (delta if backend == 'get3w' else 0)))
    return result


@pytest.mark.parametrize('delta,verdict', [(0, 'pass'), (-.1, 'regression'), (-.02, 'pass')])
def test_bootstrap(delta, verdict):
    assert compare(observations(delta=delta), samples=100)['summaries'][0]['verdict'] == verdict


def test_inconclusive():
    rows = observations()
    for i, row in enumerate(rows):
        if row['backend'] == 'get3w':
            row['score'] += -.2 if (i // 2) % 2 else .2
    assert compare(rows, samples=1000)['summaries'][0]['verdict'] == 'inconclusive'


def test_repeats_clustered_and_insufficient():
    rows = observations(20)
    rows += [{**copy.deepcopy(r), 'repetition': 1} for r in rows]
    summary = compare(rows, samples=100)['summaries'][0]
    assert summary['tasks'] == 20
    assert summary['valid_pairs'] == 40
    assert summary['verdict'] == 'insufficient_evidence'


@pytest.mark.parametrize('mutation', ['identity', 'usage', 'missing', 'infra', 'nan'])
def test_bad_pairs_never_dropped(mutation):
    rows = observations(31)
    if mutation == 'identity':
        rows[0]['identity']['runtime_version'] = 'other'
    elif mutation == 'usage':
        rows[0]['evidence']['usage_complete'] = False
    elif mutation == 'missing':
        rows.pop()
    elif mutation == 'infra':
        rows[0]['status'] = 'infrastructure_error'
    else:
        rows[0]['score'] = float('nan')
    assert compare(rows, samples=100)['summaries'][0]['verdict'] == 'not_comparable'


def test_duplicate_and_product():
    rows = observations()
    assert compare(rows, samples=100, mode='product')['summaries'][0]['verdict'] == 'descriptive_only'
    with pytest.raises(ValueError, match='duplicate'):
        compare(rows + [rows[0]], samples=100)


def test_contract_all_required():
    rows = [dict(scenario=s, status='passed', execution_mode='real_desktop', evidence={'assertion': True}) for s in SCENARIOS]
    assert contract_verdict(rows) == 'passed'
    assert contract_verdict(rows[:-1]) == 'blocked'
    rows[0]['status'] = 'failed'
    assert contract_verdict(rows) == 'failed'


def test_original_suite_and_lock(tmp_path):
    tasks = DirectorySource(ROOT / 'suites/get3w-contract-v1').tasks()
    assert len(tasks) == 60
    lock = tmp_path / 'lock.json'
    first = lock_tasks(tasks, lock, 'general', 2)
    assert len(first['tasks']) == 12
    assert lock_tasks(list(reversed(tasks)), lock, 'general', 2) == first
    assert len(verify_lock(tasks, lock)) == 12
    bad = copy.deepcopy(first)
    bad['tasks'][0]['digest'] = 'changed'
    lock.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match='corrupt'):
        verify_lock(tasks, lock)


def test_sparse_category_redistribution(tmp_path):
    tasks = DirectorySource(ROOT / 'suites/get3w-contract-v1').tasks()
    sparse = [t for t in tasks if t.category != 'Web Development'] + [next(t for t in tasks if t.category == 'Web Development')]
    assert len(lock_tasks(sparse, tmp_path / 'lock', 'general', 2)['tasks']) == 12


def test_license_and_paths(tmp_path):
    with pytest.raises(ValueError, match='authorization'):
        DirectorySource(tmp_path).tasks()
    with pytest.raises(ValueError, match='escapes'):
        contained(tmp_path, '../secret')
    (tmp_path / 'link').symlink_to('/etc/passwd')
    with pytest.raises(ValueError, match='symlinks'):
        tree_digest(tmp_path)
    for value in ('../x', '/tmp', '', 'x/y'):
        with pytest.raises(ValueError):
            safe_id(value)


def test_all_original_oracles(tmp_path):
    for task in DirectorySource(ROOT / 'suites/get3w-contract-v1').tasks():
        workspace = tmp_path / task.id
        task.copy_workspace(workspace)
        assert grade(task.root, workspace)['score'] == pytest.approx(.2)
        oracle = json.loads((task.root / 'oracle.json').read_text())
        check = oracle['checks'][0]
        (workspace / check['path']).write_text(json.dumps(check['expected']) if check['kind'] == 'json' else check['expected'])
        assert grade(task.root, workspace)['passed']
        source = oracle['checks'][1]['path']
        (workspace / source).write_text('tampered')
        assert not grade(task.root, workspace)['passed']


def test_gate_and_core():
    value = dict(schema_version=1, score=0, passed=False, cases=[dict(id='gate', weight=0, gate=True, passed=False), dict(id='result', weight=1, passed=True)])
    assert validate_grade(value)['score'] == 0
    value['score'] = 1
    with pytest.raises(ValueError):
        validate_grade(value)


@pytest.mark.parametrize('harness,events', [('pi', [{'type': 'agent_settled'}]), ('deepseek', [{'type': 'final', 'reason': {'kind': 'completed'}}]), ('opencode', [{'type': 'step_finish'}])])
def test_native_terminal(harness, events):
    assert terminal_status(harness, events, 0) == 'completed'
    assert terminal_status(harness, [], 0) == 'protocol_error'
    assert terminal_status(harness, events, 1) != 'completed'
    argv = command_for(harness, '/bin/agent', 'pinned/model', 'hello; $(no shell)', {'patch': '/state/patch'})
    assert argv[-1] == 'hello; $(no shell)'


def test_timeout(tmp_path):
    code, expired = run_process([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=.05, stdout=tmp_path/'out', stderr=tmp_path/'err')
    assert expired and code != 0


def test_redaction_and_report(tmp_path):
    assert public_config({'model': {'gateway_token': 'secret'}})['model']['gateway_token'] == '[REDACTED]'
    result = compare(observations(), samples=100)
    result['extra'] = '<script>alert(1)</script>'
    result['contracts'] = [dict(scenario='x', status='failed')]
    report(result, tmp_path)
    assert '<script>' not in (tmp_path/'index.html').read_text()
    assert 'failures="1"' in (tmp_path/'junit.xml').read_text()
    assert fingerprint(json.loads((tmp_path/'report.json').read_text())) == fingerprint(result)


def test_get3w_real_protocol(tmp_path):
    import httpx
    calls = []
    def handler(req):
        calls.append((req.method, req.url.path))
        if req.url.path == '/v1/info':
            body = dict(protocol_version=1, runtimes=[dict(harness='pi', available=True, runtime_version='1', runtime_digest='d')])
        elif req.method == 'POST' and req.url.path == '/v1/sessions':
            body = dict(session_id='s', identity={'harness': 'pi'}, environment_digest=fingerprint({'image_digest': 'pinned'}))
        elif req.url.path.endswith('/events'):
            body = dict(events=[{'type': 'final'}], cursor='1')
        elif req.method == 'GET':
            body = dict(status='completed', trace_complete=True)
        else:
            body = {}
        return httpx.Response(200, json=body)
    target = Get3WTarget(dict(url='http://bridge/', harness='pi', runtime_version='1', runtime_digest='d'), transport=httpx.MockTransport(handler))
    (tmp_path/'workspace').mkdir()
    assert target.diagnose()['status'] == 'ready'
    result = target.execute(dict(trial_id='t', instruction='hello', budget={'timeout_sec': 1}, environment={'image_digest': 'pinned'}), tmp_path)
    assert result.status == 'completed' and result.trace_complete
    target.close()
    assert ('DELETE', '/v1/sessions/s') in calls
    assert (tmp_path/'trace/events.jsonl').exists()


def test_fixture_cannot_claim_noninferiority():
    rows = observations(60)
    for row in rows:
        row['identity']['benchmark_kind'] = 'integration_fixture'
    assert compare(rows, samples=100)['summaries'][0]['verdict'] == 'fixture_only'


def test_cli_release_requires_all_harnesses(tmp_path):
    from get3w_bench.cli import main
    records = tmp_path/'results.json'
    records.write_text(json.dumps(observations()))
    contracts = tmp_path/'contracts.json'
    contracts.write_text(json.dumps([dict(scenario=s, harness='pi', status='passed', execution_mode='real_desktop', evidence={'assertions': [True]}) for s in SCENARIOS]))
    assert main(['compare', str(records), '--contracts', str(contracts), '--output', str(tmp_path/'report')]) == 2
    assert json.loads((tmp_path/'report/report.json').read_text())['release_verdict'] == 'not_passed'
