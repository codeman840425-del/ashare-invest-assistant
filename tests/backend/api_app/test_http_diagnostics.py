"""Synthetic observations only: no HTTP server, database, or business pass claim."""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location('httpdiag_controls', HERE / 'http_diagnostics.py')
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)
SENTINEL = 'SYNTHETIC_PRIVATE_SENTINEL_DO_NOT_EMIT'


class Response:
    status_code = 422
    text = 'synthetic original assertion text'

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


@pytest.mark.unit
@pytest.mark.parametrize('body', [
    SENTINEL, [SENTINEL], None, 17,
    {'error': SENTINEL},
    {'error': {'code': SENTINEL, 'message': SENTINEL, 'request_id': SENTINEL,
               'details': {'fields': [{'field': SENTINEL, 'input': SENTINEL},
                                     {'loc': ['body', SENTINEL]}, SENTINEL]}}},
    {'error': {'code': 'VALIDATION_ERROR', 'details': {'fields': [
        {'field': 'strategy_version_id', 'input': SENTINEL, 'issue': SENTINEL},
        {'loc': ['body', 'account_id'], 'ctx': {'token': SENTINEL}}]}}},
    {'items': [{'id': SENTINEL, 'cookie': SENTINEL}, {'id': SENTINEL}, SENTINEL]},
])
def test_synthetic_values_never_enter_observation(body):
    result = diag.summarize_response('reasons', Response(body),
                                     {'active': SENTINEL, 'released': 'other', 'obsolete': 'last'})
    encoded = json.dumps(result)
    assert SENTINEL not in encoded
    assert 'input' not in encoded and 'cookie' not in encoded and 'token' not in encoded
    if type(body) is dict and 'items' in body:
        assert result['item_count'] == 3 and result['id_count'] == 1
        assert result['synthetic_intersection_count'] == 1
        assert result['synthetic_hits'] == {'active': True, 'released': False, 'obsolete': False}


@pytest.mark.unit
def test_codes_and_locations_are_source_checked_public_values():
    from app.common.errors import ERROR_CODES, ErrorCode
    from app.api.v1.instances import InstanceCreate

    assert all(ERROR_CODES[ErrorCode(code)].scope == 'http' for code in diag.PUBLIC_CODES)
    assert set(InstanceCreate.model_fields) <= diag.FIELDS
    result = diag.summarize_response('etf_instance', Response({'error': {
        'code': 'VALIDATION_ERROR', 'details': {'fields': [
            {'field': 'strategy_version_id'}, {'loc': ['body', 'account_id']},
            {'field': SENTINEL}, {'loc': ['body', SENTINEL]}]}}}))
    assert result['field_locs'] == ['strategy_version_id', ['body', 'account_id'], 'unknown', 'unknown']
    assert result['error_code'] == 'VALIDATION_ERROR'
    assert diag.summarize_response(SENTINEL, Response({}))['probe'] == 'unknown'


@pytest.mark.unit
def test_unreadable_or_custom_structures_never_render_exception_or_class_name():
    class Broken:
        status_code = SENTINEL
        def json(self):
            raise ValueError(SENTINEL)
    assert diag.summarize_response('etf_search', Broken()) == {
        'probe': 'etf_search', 'status': 'unknown', 'body_type': 'unreadable'}
    custom = type(SENTINEL, (), {})()
    assert diag.summarize_response('etf_search', Response(custom))['body_type'] == 'unknown'


@pytest.mark.unit
def test_observation_flushes_without_rendering_response(monkeypatch):
    class Stream(io.StringIO):
        flushes = 0
        def flush(self):
            self.flushes += 1
    stream = Stream()
    monkeypatch.setattr(sys, 'stderr', stream)
    observer = diag.Observer(SimpleNamespace(global_and_fixture_disabled=nullcontext))
    observer.observe('etf_search', Response({'error': {'code': SENTINEL}}))
    assert stream.flushes == 1
    assert SENTINEL not in stream.getvalue()
    assert json.loads(stream.getvalue().removeprefix('HTTPDIAG '))['error_code'] == 'unknown'


def functions(path):
    return {node.name: node for node in ast.parse(path.read_text(encoding='utf-8')).body
            if isinstance(node, ast.FunctionDef)}


@pytest.mark.unit
@pytest.mark.parametrize(('filename', 'name', 'label'), [
    ('test_contract_v028_t_t23.py', 'test_06_etf_search', 'etf_search'),
    ('test_contract_v028_t_t23.py', 'test_07_etf_profile_and_datasets', 'etf_profile'),
    ('test_contract_v028_t_t23.py', 'test_09_etf_strategy_instance_scope', 'etf_instance'),
    ('test_contract_v029_t_t25.py', 'test_bc12_reasons_default_status_is_active', 'reasons'),
])
def test_actual_assertions_keep_synthetic_failure_and_emit_first(filename, name, label, monkeypatch):
    """Execute actual function AST with synthetic transport; never count as CI HTTP."""
    tree = functions(HERE / filename)
    stream = io.StringIO()
    monkeypatch.setattr(sys, 'stderr', stream)
    observer = diag.Observer(SimpleNamespace(global_and_fixture_disabled=nullcontext))
    response = Response({'error': {'code': 'VALIDATION_ERROR', 'message': SENTINEL}})
    response.status_code = 500 if label != 'reasons' else 200
    if label == 'reasons':
        response.body = {'items': [], 'next_cursor': None, 'private': SENTINEL}
    ids = {'active': 'synthetic-active', 'released': 'synthetic-released',
           'obsolete': 'synthetic-obsolete', 'signal_id': 'synthetic-signal'}
    calls = []
    def call(*args, **kwargs):
        calls.append((args, kwargs))
        return response
    def assert_err(r, status, code):
        assert r.status_code == status
        assert r.json()['error']['code'] == code
        return r.json()['error']
    namespace = {'Callable': object, 'Any': object, 'SimpleNamespace': SimpleNamespace,
                 'Rec': lambda s: call, 'require_route': lambda *a: None,
                 'seed_securities': lambda sql: None, '_seed_reasons': lambda *a: ids,
                 'O_SEARCH': '', 'O_PROFILE': '', 'O_STRATEGY': '', 'O_SIGNALS': '',
                 'ETF_CODE': 'synthetic-etf', 'DATASETS': (), '_httpdiag': diag,
                 'assert_err': assert_err}
    selected = [tree[name]] + ([tree['_reason_ids']] if label == 'reasons' else [])
    code = compile(ast.fix_missing_locations(ast.Module(body=[
        ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *selected],
        type_ignores=[])), '<actual-contract-function>', 'exec')
    exec(code, namespace)
    failures = []
    for active in (None, observer):
        token = diag._ACTIVE.set(active)
        try:
            with pytest.raises(AssertionError) as error:
                namespace[name](session=lambda: SimpleNamespace(client=None, user=SimpleNamespace(id='synthetic-user')),
                                sql=lambda *a: None, httpdiag=observer)
            failures.append(error.value.args)
        finally:
            diag._ACTIVE.reset(token)
    assert failures[0] == failures[1]
    assert len(calls) == 2 and calls[0] == calls[1]
    assert len(stream.getvalue().splitlines()) == 1
    payload = json.loads(stream.getvalue().removeprefix('HTTPDIAG '))
    assert payload['probe'] == label and SENTINEL not in stream.getvalue()
    if label == 'reasons':
        assert payload['synthetic_intersection_count'] == 0


@pytest.mark.unit
def test_real_pytest_capture_emits_before_original_failure_and_keeps_exit_one(tmp_path):
    """Child pytest fails intentionally; both fd capture and fixture capture are on."""
    child = tmp_path / 'test_synthetic_capture.py'
    child.write_text(
        'import importlib.util\nfrom pathlib import Path\n'
        f'spec = importlib.util.spec_from_file_location("child_diag", {str(HERE / "http_diagnostics.py")!r})\n'
        'diag = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(diag)\n'
        'httpdiag = diag.httpdiag\n'
        'def test_synthetic_failure(httpdiag, capfd):\n'
        '    class R:\n        status_code = 500\n'
        f'        def json(self): return {{"error": {{"code": "INTERNAL_ERROR", "message": {SENTINEL!r}}}}}\n'
        '    diag.observe_response("etf_search", R())\n'
        '    assert False, "synthetic-original-failure"\n', encoding='utf-8')
    # File stdio also works within confined hosts; no captured child pipe is needed.
    output = tmp_path / 'synthetic-child.log'
    with output.open('w', encoding='utf-8') as stream:
        result = subprocess.run([sys.executable, '-B', '-m', 'pytest', str(child), '-q', '--tb=no',
                                 '-p', 'no:cacheprovider', '-o', 'addopts='],
                                cwd=tmp_path, stdout=stream, stderr=subprocess.STDOUT, check=False)
    text = output.read_text(encoding='utf-8')
    assert result.returncode == 1
    assert SENTINEL not in text
    assert text.count('HTTPDIAG ') == 1
    assert text.index('HTTPDIAG ') < text.index('1 failed')
    assert 'Captured stderr' not in text
