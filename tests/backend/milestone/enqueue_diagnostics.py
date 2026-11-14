"""Safe observations around the original real enqueue; no replacement worker result."""
from __future__ import annotations

import json
import sys

import pytest
from sqlalchemy import func, select

from app.db.tables.realtime import pipeline_runs, suggestions
from app.db.tables.signals import candidate_signals
from app.db.tables.strategy import strategy_instances
from app.replay.baseline import require_isolated

# jobs.py:581-636 and tracking/worker.py TASK; no response-provided labels escape.
TASKS = frozenset({'daily_analysis', 'daily_report', 'tracking'})
STATUSES = frozenset({'ok', 'failed', 'unknown', 'bad_payload', 'locked'})
PIPELINE_STATUSES = ('running', 'ok', 'partial', 'failed', 'skipped')


def summarize_result(result):
    if type(result) is not list:
        return {'result_type': 'unknown'}
    rows = []
    for row in result[:20]:
        if type(row) not in (tuple, list) or len(row) != 2:
            rows.append({'task': 'unknown', 'status': 'unknown'})
            continue
        task, status = row
        rows.append({'task': task if type(task) is str and task in TASKS else 'unknown',
                     'status': status if type(status) is str and status in STATUSES else 'unknown'})
    return {'result_type': 'list', 'result_count': len(result), 'results': rows}


def counts(engine, owner):
    """Only scalar counts, on the fixture's already isolated DB; no stored JSON/error."""
    try:
        with engine.connect() as conn:
            require_isolated(conn, app_env='test')
            result = {}
            for name, table in (('instances', strategy_instances), ('candidates', candidate_signals),
                                ('suggestions', suggestions)):
                result[name] = conn.execute(select(func.count()).select_from(table).where(
                    table.c.user_id == owner)).scalar_one()
            # These counts cover this isolated DB, not just one owner's JSON stats.
            for status in PIPELINE_STATUSES:
                result['analysis_runs_' + status] = conn.execute(
                    select(func.count()).select_from(pipeline_runs).where(
                        pipeline_runs.c.step == 'tb76.daily_analysis',
                        pipeline_runs.c.status == status)).scalar_one()
            if not all(type(value) is int and value >= 0 for value in result.values()):
                return {'counts_available': False}
            return {'counts_available': True, **result}
    except Exception:
        # Diagnostic failure must not replace the original worker/DB assertion.
        return {'counts_available': False}


def enqueue_and_observe(enqueue, task, owner, *, engine, emit):
    before = counts(engine, owner)
    try:
        result = enqueue(task, owner)
    except BaseException:
        emit({'before': before, 'enqueue_raised': True})
        raise
    emit({'before': before, 'after': counts(engine, owner), **summarize_result(result)})
    return result


@pytest.fixture
def enqueue_observer(request):
    capture = request.config.pluginmanager.getplugin('capturemanager')
    def emit(payload):
        with capture.global_and_fixture_disabled():
            print('ENQUEUEDIAG ' + json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)
    def run(enqueue, task, owner, *, engine):
        return enqueue_and_observe(enqueue, task, owner, engine=engine, emit=emit)
    return run
