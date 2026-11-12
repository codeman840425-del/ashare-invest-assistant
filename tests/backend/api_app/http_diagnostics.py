"""Bounded, allowlisted HTTP observations; never render response values or errors."""
from __future__ import annotations

import json
import sys
from contextvars import ContextVar

import pytest

# Public HTTP codes in app/common/errors.py:33-99,118-187 at c9e0efc.
PUBLIC_CODES = frozenset({
    'VALIDATION_ERROR', 'INVALID_CURSOR', 'AUTH_REQUIRED', 'FORBIDDEN',
    'ACCOUNT_NOT_APPROVED', 'NOT_FOUND', 'INSTANCE_SCOPE_INVALID',
    'INTERNAL_ERROR', 'FRESH_DATA_REQUIRED', 'CALENDAR_NOT_COVERED',
    'STRATEGY_NOT_OWNED', 'STRATEGY_VERSION_NOT_RUNNABLE', 'MAINTENANCE',
})
# InstanceCreate (instances.py:288-296), legacy body, and the four original requests.
FIELDS = frozenset({'body', 'query', 'path', 'strategy_version_id', 'scope',
                    'account_id', 'security_code', 'horizon', 'param_overrides',
                    'budget_amount', 'template_id', 'q', 'types', 'status',
                    'signal_ids', 'limit', 'cursor'})
LABELS = frozenset({'etf_search', 'etf_profile', 'etf_dataset', 'index_financials',
                    'etf_instance', 'reasons'})
_ACTIVE = ContextVar('httpdiag', default=None)


def shape(value):
    for cls, label in ((dict, 'dict'), (list, 'list'), (str, 'str'), (int, 'int'),
                       (bool, 'bool'), (float, 'float'), (tuple, 'tuple'), (type(None), 'null')):
        if type(value) is cls:
            return label
    return 'unknown'


def safe_loc(value):
    if type(value) is str:
        return value if value in FIELDS else 'unknown'
    if type(value) in (list, tuple) and 0 < len(value) <= 4:
        if all(type(part) is str and part in FIELDS for part in value):
            return list(value)
    return 'unknown'


def summarize_response(label, response, synthetic_ids=None):
    out = {'probe': label if type(label) is str and label in LABELS else 'unknown'}
    status = response.status_code
    out['status'] = status if type(status) is int and 100 <= status <= 599 else 'unknown'
    try:
        body = response.json()
    except Exception:
        out['body_type'] = 'unreadable'
        return out
    out['body_type'] = shape(body)
    out['error_code'] = 'unknown'
    if type(body) is not dict:
        return out
    error = body.get('error')
    out['error_type'] = shape(error)
    if type(error) is dict:
        code = error.get('code')
        out['error_code'] = code if type(code) is str and code in PUBLIC_CODES else 'unknown'
        details = error.get('details')
        out['details_type'] = shape(details)
        if type(details) is dict:
            fields = details.get('fields')
            out['fields_type'] = shape(fields)
            if type(fields) is list:
                out['field_locs'] = [safe_loc(item.get('field', item.get('loc')))
                                     if type(item) is dict else 'unknown' for item in fields[:16]]
    if label == 'reasons':
        items = body.get('items')
        out['items_type'] = shape(items)
        if type(items) is list:
            ids = {item['id'] for item in items if type(item) is dict and type(item.get('id')) is str}
            out['item_count'] = len(items)
            out['id_count'] = len(ids)
            if type(synthetic_ids) is dict:
                out['synthetic_hits'] = {key: synthetic_ids.get(key) in ids
                                         for key in ('active', 'released', 'obsolete')
                                         if type(synthetic_ids.get(key)) is str}
                expected = {synthetic_ids[key] for key in ('active', 'released', 'obsolete')
                            if type(synthetic_ids.get(key)) is str}
                out['synthetic_intersection_count'] = len(ids & expected)
    return out


class Observer:
    def __init__(self, capturemanager):
        self.capturemanager = capturemanager
        self.synthetic_ids = None

    def observe(self, label, response):
        try:
            payload = summarize_response(label, response, self.synthetic_ids)
        except Exception:
            # An unexpected response object must not replace an original assertion.
            payload = {'probe': 'unknown', 'body_type': 'unreadable'}
        # Disables both global fd and per-test capture, so CI sees this before FAIL.
        with self.capturemanager.global_and_fixture_disabled():
            print('HTTPDIAG ' + json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)


def observe_response(label, response):
    observer = _ACTIVE.get()
    if observer is not None:
        observer.observe(label, response)


@pytest.fixture
def httpdiag(request):
    observer = Observer(request.config.pluginmanager.getplugin('capturemanager'))
    token = _ACTIVE.set(observer)
    try:
        yield observer
    finally:
        _ACTIVE.reset(token)
