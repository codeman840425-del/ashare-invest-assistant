"""Synthetic safety controls only; never execute or fake a successful real worker."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.engine import make_url

import pytest

from .enqueue_diagnostics import counts, enqueue_and_observe, summarize_result

PRIVATE = 'SYNTHETIC_PRIVATE_VALUE_NEVER_EMIT'


class UnavailableEngine:
    def connect(self):
        raise RuntimeError(PRIVATE)


@pytest.mark.unit
@pytest.mark.parametrize('result', [
    None, PRIVATE, {'task': PRIVATE},
    [(PRIVATE, PRIVATE)], [('daily_analysis', 'failed'), ('tracking', 'locked')],
    [[PRIVATE], {'task': PRIVATE}], [('daily_analysis', {'token': PRIVATE})],
])
def test_synthetic_result_projection_does_not_emit_private_values(result):
    projected = summarize_result(result)
    assert PRIVATE not in json.dumps(projected)
    if type(result) is list:
        assert projected['result_count'] == len(result)
    else:
        assert projected == {'result_type': 'unknown'}


@pytest.mark.unit
def test_source_public_worker_labels_are_explicit_and_bounded():
    result = [('daily_analysis', 'failed'), ('tracking', 'locked'), ('daily_report', 'unknown')]
    assert summarize_result(result)['results'] == [dict(zip(('task', 'status'), row)) for row in result]
    assert len(summarize_result(result * 10)['results']) == 20


@pytest.mark.unit
def test_original_callable_runs_once_and_return_identity_and_failure_assertion_survive():
    rows = [('daily_analysis', 'failed')]
    calls, observations = [], []
    owner = object()
    def original(task, actual_owner):
        calls.append((task, actual_owner))
        return rows
    actual = enqueue_and_observe(original, 'daily_analysis', owner,
                                  engine=UnavailableEngine(), emit=observations.append)
    assert actual is rows
    assert calls == [('daily_analysis', owner)]
    for result in (rows, actual):
        with pytest.raises(AssertionError):
            assert result == [('daily_analysis', 'ok')]
    assert len(observations) == 1
    assert observations[0]['before'] == observations[0]['after'] == {'counts_available': False}
    assert PRIVATE not in json.dumps(observations)


@pytest.mark.unit
def test_original_exception_is_reraised_without_printing_exception_or_owner():
    error = RuntimeError(PRIVATE)
    observations = []
    def original(task, owner):
        raise error
    with pytest.raises(RuntimeError) as raised:
        enqueue_and_observe(original, PRIVATE, PRIVATE,
                            engine=UnavailableEngine(), emit=observations.append)
    assert raised.value is error
    assert observations == [{'before': {'counts_available': False}, 'enqueue_raised': True}]
    assert counts(UnavailableEngine(), PRIVATE) == {'counts_available': False}
    assert PRIVATE not in json.dumps(observations)


@pytest.mark.unit
def test_count_projection_reads_only_isolated_scalar_counts_and_closes_connection():
    statements, closed = [], []
    url = make_url('postgresql+psycopg://synthetic@/tb70_synthetic?host=/tmp/tb70-synthetic')
    def execute(statement):
        statements.append(str(statement))
        value = 'tb70_synthetic' if len(statements) == 1 else 3
        return SimpleNamespace(scalar_one=lambda: value)
    class Engine:
        @contextmanager
        def connect(self):
            try:
                yield SimpleNamespace(engine=SimpleNamespace(url=url), execute=execute)
            finally:
                closed.append(True)
    observed = counts(Engine(), PRIVATE)
    assert closed == [True] and observed['counts_available'] is True
    assert len(statements) == 9 and statements[0] == 'select current_database()'
    assert all('count(*)' in sql.lower() for sql in statements[1:])
    assert all('stats' not in sql and 'error' not in sql for sql in statements)
    assert PRIVATE not in json.dumps(observed)
    assert all(value == 3 for key, value in observed.items() if key != 'counts_available')


@pytest.mark.unit
def test_actual_pytest_fd_capture_flushes_observation_before_original_failure(tmp_path):
    module_path = Path(__file__).with_name('enqueue_diagnostics.py')
    child = tmp_path / 'test_synthetic_enqueue.py'
    child.write_text(
        'import importlib.util\n'
        f'spec = importlib.util.spec_from_file_location("enqueue_diag_child", {str(module_path)!r})\n'
        'diag = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(diag)\n'
        'enqueue_observer = diag.enqueue_observer\n'
        'def test_original_failed_assertion(enqueue_observer, capfd):\n'
        '    class Engine:\n'
        f'        def connect(self): raise RuntimeError({PRIVATE!r})\n'
        '    def original(task, owner): return [(task, "failed")]\n'
        f'    assert enqueue_observer(original, "daily_analysis", {PRIVATE!r}, engine=Engine()) == [("daily_analysis", "ok")]\n',
        encoding='utf-8')
    output = tmp_path / 'child.log'
    with output.open('w', encoding='utf-8') as stream:
        process = subprocess.run([sys.executable, '-B', '-m', 'pytest', str(child), '-q', '--tb=no',
                                  '-p', 'no:cacheprovider', '-o', 'addopts='], cwd=tmp_path,
                                 stdout=stream, stderr=subprocess.STDOUT, check=False,
                                 env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[3] / 'src/backend'),
                                      'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'})
    text = output.read_text(encoding='utf-8')
    assert process.returncode == 1
    assert PRIVATE not in text and 'Captured stderr' not in text
    assert text.count('ENQUEUEDIAG ') == 1
    assert text.index('ENQUEUEDIAG ') < text.index('1 failed')
