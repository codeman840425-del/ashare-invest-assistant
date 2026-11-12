"""Current §7.9 admin contracts: real route/auth negatives and isolated DB reads.

No decision or lifecycle approval is performed. Offline negatives override only
storage boundaries; production current_admin/human_admin and error rendering run.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.promotions import DecisionRequest, LifecycleRequest
from app.auth.deps import get_engine, get_session_store

_spec = importlib.util.spec_from_file_location('current_admin_auth_fixtures', Path(__file__).with_name('test_auth_t_b03.py'))
_auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_auth)
authdb = _auth.authdb
sql = _auth.sql
app_client = _auth.app_client
mkuser = _auth.mkuser
session = _auth.session

ADMIN_ENDPOINTS = [
    ('GET', '/admin/promotions'),
    ('GET', '/admin/securities/reconciliation'),
    ('POST', '/admin/promotions/{review_id}/decision'),
    ('POST', '/admin/strategies/{strategy_id}/versions/{version_id}/lifecycle'),
]


def request_path(path):
    return '/api/v1' + path.format(review_id=uuid.uuid4(), strategy_id=uuid.uuid4(), version_id=uuid.uuid4())


def negative_body(path):
    # Nonexistent UUID targets, only rejection cases; never submit an approval.
    if path.endswith('/decision'):
        return {'decision': 'rejected', 'comment': 'synthetic denial control', 'ack_warn_gates': [], 'password': 'synthetic-denial-only'}
    return {'to': 'retired', 'reason': 'synthetic denial control', 'review_id': None, 'password': 'synthetic-denial-only'}


@pytest.mark.unit
@pytest.mark.parametrize(('method', 'path'), ADMIN_ENDPOINTS)
def test_current_admin_routes_hide_without_session(backend, make_settings, method, path):
    app = backend.main.create_app(make_settings())
    class ForbiddenEngine:
        def __getattr__(self, name):
            pytest.fail('Unauthenticated admin request reached database')
    app.dependency_overrides[get_engine] = lambda: ForbiddenEngine()
    app.dependency_overrides[get_session_store] = lambda: SimpleNamespace(get=lambda sid: None)
    client = TestClient(app)
    try:
        response = client.request(method, request_path(path), json=negative_body(path) if method == 'POST' else None)
        _auth.assert_err(response, 404, 'NOT_FOUND')
        assert response.headers['content-type'] == 'application/json; charset=utf-8'
    finally:
        client.close()


@pytest.mark.unit
def test_admin_coverage_guard_still_rejects_missing_contract_references(backend, make_settings, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('admin_coverage_negative_control', Path(__file__).with_name('test_contract_v028_t_t23.py'))
    coverage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(coverage)
    monkeypatch.setattr(coverage, 'TESTS_DIR', tmp_path)
    with pytest.raises(AssertionError, match='这些管理端接口没有契约测试') as error:
        coverage.test_05_every_mounted_admin_endpoint_has_contract_test(backend, make_settings)
    for method, path in ADMIN_ENDPOINTS:
        assert f'{method} {path}' in str(error.value)


@pytest.mark.integration
@pytest.mark.contract
@pytest.mark.parametrize(('method', 'path'), ADMIN_ENDPOINTS)
def test_current_admin_routes_hide_from_real_nonadmin_session(session, method, path):
    signed = session()
    response = signed.client.request(method, request_path(path), json=negative_body(path) if method == 'POST' else None,
                                     headers={'X-CSRF-Token': signed.csrf})
    error = _auth.assert_err(response, 404, 'NOT_FOUND')
    assert set(error) <= {'code', 'message', 'details', 'request_id'}


@pytest.mark.integration
@pytest.mark.contract
@pytest.mark.parametrize('path', ['/admin/promotions', '/admin/securities/reconciliation'])
def test_current_admin_read_lists_paginate_and_reject_bad_filters(session, mkuser, path):
    signed = session(mkuser(role='admin'))
    response = signed.client.get('/api/v1' + path)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {'items', 'next_cursor'}
    assert isinstance(body['items'], list)
    assert body['next_cursor'] is None or isinstance(body['next_cursor'], str)
    invalid = {'decision': 'unknown'} if path.endswith('/promotions') else {'status': 'unknown'}
    _auth.assert_err(signed.client.get('/api/v1' + path, params=invalid), 400, 'VALIDATION_ERROR')


@pytest.mark.integration
@pytest.mark.contract
@pytest.mark.parametrize('path', ['/admin/promotions/{review_id}/decision', '/admin/strategies/{strategy_id}/versions/{version_id}/lifecycle'])
def test_admin_mutations_reject_token_style_requests_before_decision(session, mkuser, path):
    signed = session(mkuser(role='admin'))
    response = signed.client.post(request_path(path), json=negative_body(path),
                                  headers={'X-CSRF-Token': signed.csrf, 'Authorization': 'Bearer synthetic-denial-only'})
    _auth.assert_err(response, 403, 'HUMAN_SESSION_REQUIRED')


@pytest.mark.unit
@pytest.mark.parametrize('model', [DecisionRequest, LifecycleRequest])
def test_admin_mutation_password_is_required_and_never_serialized(model):
    path = '/decision' if model is DecisionRequest else '/lifecycle'
    payload = negative_body(path)
    body = model.model_validate(payload)
    assert 'password' not in body.model_dump()
    assert payload['password'] not in repr(body)
    del payload['password']
    with pytest.raises(ValidationError):
        model.model_validate(payload)
