"""T-T22安全适配：仅校准3个陈旧基准，其余原断言与真实helper保留。

来源为T-T21固定e6eaeb2的同名selfchecks；使用 -p tt21_plugin 与同一审计入口。
不执行正式卡/共享库；等待T-B88交付通知后才运行这3例。
"""
from __future__ import annotations

from selfchecks import test_ta16_policy_confidence as _policy
from selfchecks import test_tb76_assembly as _assembly
from selfchecks import test_tb77_aggregates as _aggregates
from selfchecks.test_tb70_replay import integration, no_network  # noqa: F401
from selfchecks.test_tb74_candidates import setup  # noqa: F401

def test_actual_isolated_seed_idempotence_and_same_version_conflict(integration: _policy.Any) -> None:
    engine, *_ = integration
    original = _policy.load(_policy.CONFIG)
    with engine.connect() as conn:
        transaction = conn.begin()
        row = conn.execute(_policy.select(_policy.engine_policies).where(_policy.engine_policies.c.version_no == original.version_no)).first()
        inserted = _policy.seed(conn, original)
        assert inserted is (row is None)
        assert _policy.seed(conn, original) is False
        _policy.check(conn, original)
        bad = _policy.copy.deepcopy(original.model_dump())
        bad['system_components'][0]['version_no'] += 1
        altered = _policy.EnginePolicyReference.model_validate(bad)
        with _policy.pytest.raises(ValueError, match='engine_policy_version_hash_conflict'):
            _policy.seed(conn, altered)
        with _policy.pytest.raises(ValueError, match='engine_policy_version_hash_conflict'):
            _policy.check(conn, altered)
        transaction.rollback()

def test_real_worker_policy_bound_candidate_suggestion_and_idempotence(setup: _assembly.Any) -> None:
    engine, client, stranger, owner, *_ = setup
    expected = _assembly.load_policy(_assembly.ROOT / 'config')
    alternate_version = expected.version_no + 1
    instance = _assembly.prepare(setup)
    assert _assembly.enqueue(_assembly.ANALYZE, owner) == [(_assembly.ANALYZE, 'ok')]
    with engine.connect() as conn:
        candidate = conn.execute(_assembly.select(_assembly.candidate_signals).where(_assembly.candidate_signals.c.instance_id == instance)).one()
        row = conn.execute(_assembly.select(_assembly.suggestions).where(_assembly.suggestions.c.user_id == owner)).one()
        assert row.engine_policy_id is not None
        snapshot = conn.execute(_assembly.select(_assembly.data_snapshots).where(_assembly.data_snapshots.c.id == candidate.snapshot_id)).one()
        assert snapshot.items['engine_policy_version_no'] == expected.version_no
        assert snapshot.items['content_sha256']
        assert _assembly.Decimal(snapshot.items['market_facts']['price']) > 0
        sid, cid = (str(row.id), str(candidate.id))
    response = client.get('/api/v1/suggestions/' + sid)
    assert response.status_code == 200
    body = response.json()
    assert body['engine_policy']['content_sha256'] == snapshot.items['content_sha256']
    confidence = body['strategies'][0]['confidence']
    c = confidence['components']
    value = (_assembly.Decimal('.5') * _assembly.Decimal(str(c['data_completeness'])) + _assembly.Decimal('.3') * _assembly.Decimal(str(c['dimension_agreement'] or 0)) + _assembly.Decimal('.2') * _assembly.Decimal(str(c['condition_margin'] or 0))).quantize(_assembly.Decimal('.01'), rounding=_assembly.ROUND_HALF_UP)
    assert _assembly.Decimal(str(confidence['value'])) == value
    assert body['strategies'][0]['candidate_signal_id'] == cid
    assert stranger.get('/api/v1/suggestions/' + sid).status_code == 404
    assert _assembly.enqueue(_assembly.ANALYZE, owner) == [(_assembly.ANALYZE, 'ok')]
    with engine.connect() as conn:
        assert len(conn.execute(_assembly.select(_assembly.suggestions).where(_assembly.suggestions.c.user_id == owner)).all()) == 1
        assert len(conn.execute(_assembly.select(_assembly.candidate_signals).where(_assembly.candidate_signals.c.instance_id == instance)).all()) == 1
    assert _assembly.enqueue(_assembly.REPORT, owner) == [(_assembly.REPORT, 'ok')]
    report = client.get('/api/v1/daily-reports/2026-10-30').json()
    assert report['stocks'][0]['suggestion_id'] == sid
    assert report['evidence']
    assert all((e['id'].startswith('688018.SH:') for e in report['evidence']))
    from app.engine_policies import EnginePolicyReference
    from app.suggestions.models import SuggestionInput
    from app.suggestions.service import archive, snapshot_items
    with engine.connect() as conn:
        transaction = conn.begin()
        original = conn.execute(_assembly.select(_assembly.data_snapshots).where(_assembly.data_snapshots.c.id == row.snapshot_id)).one()
        raw = _assembly.load_policy(_assembly.ROOT / 'config').model_dump()
        raw['version_no'] = alternate_version
        raw['system_components'][0]['version_no'] += 1
        policy = EnginePolicyReference.model_validate(raw)
        _assembly.seed(conn, policy)
        from app.db.tables.strategy import engine_policies
        pid = conn.execute(_assembly.select(engine_policies.c.id).where(engine_policies.c.version_no == alternate_version)).scalar_one()
        content = SuggestionInput.model_validate({**original.items['input'], 'engine_policy_id': pid, 'snapshot_id': _assembly.uuid.uuid4()})
        conn.execute(_assembly.insert(_assembly.data_snapshots).values(id=content.snapshot_id, user_id=owner, purpose='signal', hash=content.snapshot_id.hex, items=snapshot_items(content), created_at=content.created_at))
        with _assembly.pytest.raises(ValueError, match='candidate_policy_snapshot_mismatch'):
            archive(conn, user_id=owner, content=content)
        transaction.rollback()

def test_routes_real_ownership_unread_and_imported_holdings(integration: _aggregates.Any, no_network: _aggregates.Any) -> None:
    engine, client, stranger, user_id, other_id = integration
    account = client.post('/api/v1/accounts', json={'broker_name': '合成券商', 'alias': '合成'})
    assert account.status_code == 201
    account_id = account.json()['id']
    assert stranger.get('/api/v1/terminal', params={'account_id': account_id}).status_code == 404
    with engine.begin() as conn:
        seed = _aggregates.load_reference_file(_aggregates.Path(_aggregates.__file__).resolve().parents[3] / 'config', 'trading_calendar.json')
        assert isinstance(seed, _aggregates.CalendarReference)
        _aggregates.seed_calendar(conn, seed)
    with engine.begin() as conn:
        for owner in (user_id, other_id):
            conn.execute(_aggregates.insert(_aggregates.notifications).values(id=_aggregates.uuid.uuid4(), user_id=owner, kind=next(iter(_aggregates.NotificationKind)).value, severity=next(iter(_aggregates.Severity)).value, title='合成通知'))
    for path in ('/terminal', '/today', '/market/overview'):
        response = client.get('/api/v1' + path)
        assert response.status_code == 200, response.status_code
        value = response.json()
        assert value['data_status'] in {'partial', 'unavailable'}
        assert value['gaps']
        cached = client.get('/api/v1' + path, headers={'If-None-Match': response.headers['etag']})
        assert cached.status_code == 304
        if path != '/market/overview':
            assert value['unread_notifications'] == 1
        else:
            assert value['breadth'] is None
            assert value['regime'] is None
            assert value['indices'] == []
    today = client.get('/api/v1/today').json()
    for key in ('alerts', 'plan_triggers', 'risk_flags', 'released_reasons', 'pending_plan_drafts', 'invalidations_today'):
        assert today[key] == {'items': [], 'more': False}
    assert today['daily_report']['status'] == 'not_yet'
    uploaded = client.post('/api/v1/imports', data={'account_id': account_id, 'kind': 'positions', 'snapshot_as_of': '2026-10-21T08:00:00Z'}, files={'file': ('synthetic.txt', _aggregates.positions_file(), 'text/plain')})
    assert uploaded.status_code == 201
    confirmed = client.post(f"/api/v1/imports/{uploaded.json()['batch_id']}/confirm", json={'mode': 'all', 'acknowledge_warnings': True}, headers={'Idempotency-Key': _aggregates.uuid.uuid4().hex})
    assert confirmed.status_code == 200
    terminal = client.get('/api/v1/terminal').json()
    assert {row['security_code'] for row in terminal['rows']} == {'688018.SH', '688073.SH', '300364.SZ', '301218.SZ'}
    assert all((row['holding'] and row['quote'] is None and (row['suggestion'] is None) for row in terminal['rows']))
    assert terminal['account']['pnl_day'] is None
    assert client.get('/api/v1/terminal', params={'scope': 'invalid'}).status_code == 400
    second = client.post('/api/v1/accounts', json={'broker_name': '合成券商', 'alias': '另一个合成'})
    assert second.status_code == 201
    chosen = client.get('/api/v1/terminal')
    assert chosen.status_code == 200
    assert chosen.json()['account_id'] == account_id
    assert client.get('/api/v1/today', params={'account_id': second.json()['id']}).status_code == 200
    assert client.get('/api/v1/terminal', params={'account_id': account_id}).status_code == 200
    with engine.begin() as conn:
        conn.execute(_aggregates.insert(_aggregates.alerts).values(id=_aggregates.uuid.uuid4(), user_id=user_id, severity=next(iter(_aggregates.Severity)).value, triggered_at=_aggregates.dt.datetime.now(_aggregates.dt.UTC)))
    nonempty = client.get('/api/v1/terminal', params={'account_id': account_id})
    assert nonempty.status_code == 200
    actual = nonempty.json()
    _aggregates.Terminal.model_validate(actual)
    assert actual['account_id'] == account_id
    assert actual['data_status'] in {'partial', 'unavailable'}
    assert actual['gaps']
    assert {row['security_code'] for row in actual['rows']} == {'688018.SH', '688073.SH', '300364.SZ', '301218.SZ'}
    assert all((row['holding'] for row in actual['rows']))
    assert actual['unread_notifications'] == 1
    from fastapi.testclient import TestClient
    with TestClient(client.app) as anonymous:
        assert anonymous.get('/api/v1/terminal').status_code == 401
    assert no_network == []
