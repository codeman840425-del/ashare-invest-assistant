"""First slice only: real import/API/queue/worker/SQL, wholly fictional inputs.

Run using run_p2n10.py with separately provisioned, identity-checked Unix services.
No formal cards or production credentials are opened. SecondSliceSkeleton is not
collected and makes no acceptance claim. 24 schema cases are NOT business PIT tests.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
import redis
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.tables.market import securities
from app.db.tables.realtime import (
    daily_reports,
    pipeline_runs,
    suggestion_tracking,
    suggestions,
)
from app.db.tables.research import watchlist_items
from app.db.tables.reviews import data_snapshots
from app.db.tables.signals import candidate_signals, plan_drafts
from app.db.tables.strategy import feature_catalog, risk_events
from app.main import create_app
from app.reports import dimensions as dim
from app.reports.models import DailyDimensionAnalysis, DailyReport
from app.tracking.worker import TASK as TRACK
from app.workers import jobs
from app.workers.daily import ANALYZE, REPORT
from psycopg import sql
from selfchecks import test_p2n02_risk_controls as shared
from selfchecks import test_p2n03_tracking as tracking
from selfchecks import test_p2n04_daily_dimensions as daily
from selfchecks import test_tb78_acceptance as core
from selfchecks.test_tb89_full_migrations import deploy_grants
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

ROOT = Path(__file__).resolve().parents[3]
INPUTS = json.loads((Path(__file__).parent / "fixtures/p2n10_inputs.json").read_text())
F23 = dim.GROUPS["news"][
    0
]  # canonical public feature identifier, not an API credential
DIMENSIONS = [
    "technical",
    "capital",
    "fundamental",
    "sentiment",
    "sector_market",
    "news",
]


def artifacts() -> Path:
    path = Path(os.environ["P2N10_ARTIFACTS"]).resolve()
    assert path.is_dir(), "Explicit private P2N10 artifacts directory is required"
    return path


def verify_services() -> Path:
    # T-T21: identity/mounts pinned by host preflight; recheck both real Unix sockets.
    if "tt21_closeout" in sys.modules:  # Preserve the dedicated runner's live adapter.
        from tt21_closeout import verify_services as checked
    else:
        from .tt21_closeout import verify_services as checked
    return checked()


@pytest.fixture(scope="module")
def database():
    verify_services()
    cache = redis.Redis.from_url(
        "unix:///tmp/tb91-owned-redis/redis.sock?db=15"
    )
    cache.flushdb()  # adapter deletes this run's physical prefix only, never shared FLUSHDB
    name = "tb70_p2n10_" + uuid.uuid4().hex
    ci_receipt = None
    ci_created = set()
    if "AIA_CI_UNIX_RECEIPT" in os.environ:
        from . import ci_unix_identity as ci_identity
        ci_receipt, ci_artifacts = ci_identity.verify()
        logical_name = name
        name = ci_identity.owned_name(ci_receipt, logical_name)
    socket_path = json.loads((artifacts() / "isolation.json").read_text())[0]["mounts"][
        0
    ]["Source"]
    url = "postgresql+psycopg://postgres@/" + name + "?host=" + socket_path
    with psycopg.connect(
        dbname="postgres", user="postgres", host=socket_path, autocommit=True
    ) as admin:
        assert admin.execute("SHOW listen_addresses").fetchone() == ("",)
        if ci_receipt is not None:
            from .ci_owned_database import create_owned_database
            created_name = create_owned_database(admin, ci_receipt, logical_name, ci_created)
            assert created_name == name
        else:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            if ci_receipt is not None:
                ci_identity.require_owned_database(ci_receipt, logical_name, name, ci_created)
                ci_identity.save_database_event(ci_artifacts, ci_receipt, logical_name, name, "created")
                with psycopg.connect(dbname=name, user="postgres", host=socket_path) as owned:
                    assert owned.execute("SELECT current_database()").fetchone() == (name,)
            else:
                if "tt21_closeout" in sys.modules:
                    from tt21_closeout import own_name
                else:
                    from .tt21_closeout import own_name
                # Preserve the legacy resource adapter's original mapping.
                url = url.replace("/" + name + "?", "/" + own_name(name) + "?")
            cfg = Config()
            cfg.set_main_option("script_location", str(ROOT / "src/backend/migrations"))
            graph = ScriptDirectory.from_config(cfg)
            heads = graph.get_heads()
            assert len(heads) == 1, "Unique frozen-source migration head is required"
            assert len(list(graph.walk_revisions())) > 0
            cfg.cmd_opts = Namespace(x=["url=" + url])
            command.upgrade(cfg, "head")
            engine = create_engine(url, hide_parameters=True)
            try:
                with engine.begin() as conn:
                    assert (
                        conn.exec_driver_sql(
                            "SELECT version_num FROM alembic_version"
                        ).scalar_one()
                        == heads[0]
                    )
                    if ci_receipt is not None:
                        from .ci_owned_database import deploy_owned_grants
                        deploy_owned_grants(conn, ci_receipt, logical_name, name, ci_created)
                    else:
                        deploy_grants(conn)
                    for code in shared.CODES:
                        conn.execute(
                            insert(securities).values(
                                code=code,
                                name="TEST纯合成",
                                type="stock",
                                exchange=code[-2:],
                                board="star" if code.startswith("688") else "chinext",
                                listing_status="listed",
                            )
                        )
            finally:
                engine.dispose()
            yield url.replace("postgres@", "aia_api@")
        finally:
            try:
                cache.flushdb()
            finally:
                cache.close()
                # Business transactions commit only to THIS disposable database.
                if ci_receipt is not None:
                    ci_identity.verify()  # Live identity before destructive cleanup.
                    ci_identity.require_owned_database(ci_receipt, logical_name, name, ci_created)
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
                if ci_receipt is not None:
                    ci_created.remove(name)
                    ci_identity.save_database_event(ci_artifacts, ci_receipt, logical_name, name, "dropped")
                (artifacts() / "database-cleanup.json").write_text(
                    json.dumps(
                        {
                            "dedicated_database_dropped": True,
                            "real_application_transactions": True,
                        }
                    )
                )


@pytest.fixture(scope="module")
def synthetic_users(database, tmp_path_factory):
    old = shared.REDIS
    shared.REDIS = (
        "unix:///tmp/tb91-owned-redis/redis.sock?db=15"
    )
    gen = shared.env.__wrapped__(database, tmp_path_factory.mktemp("p2n10-import"))
    try:
        result = next(gen)
        yield result
    finally:
        try:
            next(
                gen, None
            )  # execute native client/engine cleanup, not generator.close()
        finally:
            shared.REDIS = old


def enqueue(settings, owner, task, **payload):
    client = redis.Redis.from_url(settings.redis_url)
    try:
        assert client.llen(jobs.QUEUE_KEY) == 0
        jobs._push(client, task, {"user_id": str(owner), **payload})
        result = jobs.worker_tick(settings, client=client)
        assert result == [(task, "ok")], (task, result)
        return result
    finally:
        client.close()


@pytest.fixture(scope="module")
def loop(synthetic_users):
    env = synthetic_users
    engine, _client, _stranger, owner, _other, settings = env
    chain = core.chain.__wrapped__(
        env[:5]
    )  # real fictional upload/preview/confirm, no stored output fixtures
    account = chain[0][5]
    published = core.mount(chain, version_no=2)
    simulated = core.mount(chain, version_no=3, lifecycle="simulating")
    missing = core.mount(chain, version_no=4, source_gate_key=F23)
    with engine.begin() as conn:
        conn.execute(
            pg_insert(feature_catalog)
            .values(
                feature_key="f.close_qfq",
                status="verified_live",
                source={"synthetic": True},
                unit="CNY/share",
            )
            .on_conflict_do_nothing()
        )
        conn.execute(
            pg_insert(feature_catalog)
            .values(
                feature_key=F23,
                status="declared",
                source={"synthetic": True},
                unit="count",
            )
            .on_conflict_do_nothing()
        )
        conn.execute(
            insert(watchlist_items).values(
                id=uuid.uuid4(), user_id=owner, security_code="688073.SH"
            )
        )
    # Real registered business handler, as in delivered P2N03/04 facilities.
    # Seeding market follows generation, before explicitly enqueuing tracking;
    # do not prematurely auto-track missing future market data via the generic tick.
    assert (
        jobs.TASKS[ANALYZE](settings, user_id=str(owner), trade_date=str(daily.DATE))
        == 1
    )
    with engine.connect() as conn:
        suggestion = conn.execute(
            select(suggestions).where(suggestions.c.user_id == owner)
        ).one()
        candidates = {
            str(r.instance_id): r
            for r in conn.execute(
                select(candidate_signals).where(candidate_signals.c.user_id == owner)
            )
        }
    assert {published, simulated} <= candidates.keys()
    marker = int(
        next(r["operand"] for r in INPUTS if r["label"] == "TEST-fundamental-present")
    )
    daily.source(env, marker=marker)
    enqueue(settings, owner, REPORT, trade_date=str(daily.DATE))
    at = tracking.seed_market(env, suggestion)
    enqueue(settings, owner, TRACK, as_of=at.isoformat())
    yield SimpleNamespace(
        env=env,
        account=account,
        suggestion=suggestion,
        published=candidates[published],
        simulated=candidates[simulated],
        missing=missing,
        candidates=candidates,
        at=at,
    )


def count(conn, table, owner):
    return conn.execute(
        select(func.count()).select_from(table).where(table.c.user_id == owner)
    ).scalar_one()


def test_daily_risk_tracking_loop(loop):
    engine, client, stranger, owner, _, settings = loop.env
    report_url = "/api/v1/daily-reports/" + str(daily.DATE)
    response = client.get(report_url)
    assert response.status_code == 200
    DailyReport.model_validate_json(response.content)
    report = response.json()
    violations = []
    assert report["data_status"] == "partial" and report["gaps"]
    assert {r["security_code"] for r in report["stocks"]} == {"688018.SH", "688073.SH"}
    evidence = {e["id"]: e for e in report["evidence"]}
    stock = next(r for r in report["stocks"] if r["security_code"] == "688018.SH")
    assert stock["suggestion_id"] == str(loop.suggestion.id)
    for row in report["stocks"]:
        assert [d["dimension"] for d in row["dimensions"]] == DIMENSIONS
        assert row["analysis_snapshot_id"]
        for d in row["dimensions"]:
            for item in d["facts"] + d["feature_refs"]:
                assert set(item["evidence_ids"]) <= evidence.keys()
                assert all(
                    i.startswith(row["security_code"] + ":")
                    for i in item["evidence_ids"]
                )
            if d["data_status"] == "unavailable":
                assert d["facts"] == [] and d["data_as_of"] is None and d["gaps"]
    groups = {d["dimension"]: d for d in stock["dimensions"]}
    assert groups["technical"]["facts"] and groups["fundamental"]["facts"]
    assert evidence["688018.SH:dimension:f.ann_risk_count_10d"]["value"] is None
    f23 = next(
        f
        for f in groups["news"]["feature_refs"]
        if f["feature_key"] == "f.ann_risk_count_10d"
    )
    assert f23["status"] == "declared", (
        "Having an announcement must not upgrade the classifier"
    )
    # G2 source rejection happens BEFORE candidate creation; absence is required,
    # not a fabricated blocked candidate or an empty-success acceptance.
    assert loop.missing not in loop.candidates
    with engine.connect() as conn:
        run = conn.execute(
            select(pipeline_runs)
            .where(pipeline_runs.c.step == "tb76." + ANALYZE)
            .order_by(pipeline_runs.c.started_at.desc())
        ).first()
        outcome = run.stats["users"][str(owner)]
        assert any(
            i.startswith("runtime_source_gate:") and F23 in i for i in outcome["issues"]
        )
        assert any(b["instance_id"] == loop.missing for b in outcome["bindings"])
        assert all(e["instance_id"] != loop.missing for e in outcome["evaluations"])
    (artifacts() / "missing-source-observed.json").write_text(
        json.dumps(
            {
                "real_worker_source_gate_recorded": True,
                "no_candidate_created": True,
                "no_evaluation_published": True,
            }
        )
    )
    # Conservative top-level timestamp, never generation time (T-A29).
    components = [report.get("market"), report.get("account"), *report["stocks"]]
    components += [d for r in report["stocks"] for d in r["dimensions"]]
    stamps = [
        dt.datetime.fromisoformat(c["data_as_of"])
        for c in components
        if c and c.get("data_as_of")
    ]
    (artifacts() / "daily-timestamp-observed.json").write_text(
        json.dumps(
            {
                "actual": report["data_as_of"],
                "expected_earliest_component": min(stamps).isoformat()
                if stamps
                else None,
                "known_components": len(stamps),
            }
        )
    )
    assert stamps
    if not isinstance(report["data_as_of"], str) or dt.datetime.fromisoformat(
        report["data_as_of"]
    ) != min(stamps):
        violations.append(
            "T-A29: report data_as_of must equal earliest known component, actual null/mismatch"
        )
    with engine.connect() as conn:
        stored = conn.execute(
            select(daily_reports).where(daily_reports.c.user_id == owner)
        ).one()
        for row in report["stocks"]:
            snapshot = conn.execute(
                select(data_snapshots).where(
                    data_snapshots.c.id == uuid.UUID(row["analysis_snapshot_id"])
                )
            ).one()
            assert snapshot.user_id == owner
            assert dim.digest(snapshot._mapping["items"]) == snapshot.hash
            assert snapshot._mapping["items"]["account_id"] == report["account_id"]
            assert snapshot._mapping["items"]["sources"]
        original_body = stored.body
    assert stranger.get(report_url).status_code == 404
    assert stranger.get("/api/v1/daily-reports").json()["items"] == []

    evaluation_url = (
        "/api/v1/risk-controls/evaluation?security_code=688018.SH&account_id="
        + str(loop.account)
    )
    with engine.connect() as conn:
        before_events = count(conn, risk_events, owner)
    evaluated = client.get(evaluation_url)
    assert evaluated.status_code == 200
    risk = evaluated.json()
    assert len(risk["controls"]) == 6 and risk["gaps"]
    rc3 = next(c for c in risk["controls"] if c["control"] == "total_exposure")
    assert rc3["state"] == "unknown" and rc3["gaps"]
    assert all(not f["gated_actions"] for f in rc3["flags"])
    assert stranger.get(evaluation_url).status_code == 404
    with engine.connect() as conn:
        assert count(conn, risk_events, owner) == before_events

    # The very same generated candidates, not manually assembled response bodies.
    for candidate, expected in [(loop.simulated, "STRATEGY_VERSION_NOT_RUNNABLE")]:
        endpoint = "/api/v1/candidate-signals/" + str(candidate.id)
        actual = client.get(endpoint)
        assert actual.status_code == 200
        assert actual.json()["lifecycle"] == "simulating"
        confidence = actual.json()["confidence"]["value"]
        if type(confidence) not in (int, float):
            violations.append(
                "CandidateSignal.confidence.value must be JSON number; actual "
                + type(confidence).__name__
            )
        rejected = client.post(
            "/api/v1/plan-drafts", json={"signal_ids": [str(candidate.id)]}
        )
        simulation_protection = (
            rejected.status_code == 409
            and rejected.json().get("error", {}).get("code") == expected
        )
        if not simulation_protection:
            violations.append(
                "simulating POST /plan-drafts expected 409 STRATEGY_VERSION_NOT_RUNNABLE; actual "
                + str(rejected.status_code)
            )
        assert stranger.get(endpoint).status_code == 404
        (artifacts() / "candidate-contract-observed.json").write_text(
            json.dumps(
                {
                    "confidence_value": confidence,
                    "confidence_type": type(confidence).__name__,
                    "plan_post_status": rejected.status_code,
                    "expected_status": 409,
                    "expected_error": expected,
                },
                indent=2,
            )
        )
    with engine.connect() as conn:
        assert count(conn, plan_drafts, owner) == 0

    tracking_url = "/api/v1/suggestions/" + str(loop.suggestion.id) + "/tracking"
    tracked = client.get(tracking_url)
    assert tracked.status_code == 200
    data = tracked.json()
    expected_versions = {r["strategy_version_id"] for r in loop.suggestion.strategies}
    complete = [r for r in data["results"] if r["state"] == "complete"]
    assert complete and {r["horizon_days"] for r in complete} == {1, 5, 20}
    assert {r["strategy_version_id"] for r in complete} == expected_versions
    assert len(complete) == 3 * len(expected_versions)
    for r in complete:
        assert r["entry_at"] and r["exit_at"] and r["price_basis"] == "qfq"
        assert r["return_pct"] is not None and r["max_drawdown_pct"] is not None
        assert set(r["evidence_ids"]) <= {e["id"] for e in r["evidence"]}
    for n in [1, 5, 20]:
        assert 0 < data["t" + str(n)]["n"] < 5
        assert data["t" + str(n)]["value"] is None
    assert stranger.get(tracking_url).status_code == 404
    with engine.connect() as conn:
        before = {
            r.horizon_days: r.snapshot_id
            for r in conn.execute(
                select(suggestion_tracking).where(
                    suggestion_tracking.c.suggestion_id == loop.suggestion.id
                )
            )
        }
    assert set(before) == {1, 5, 20}
    enqueue(settings, owner, TRACK, as_of=(loop.at + dt.timedelta(days=1)).isoformat())
    assert client.get(tracking_url).json() == data
    enqueue(settings, owner, REPORT, trade_date=str(daily.DATE))
    assert client.get(report_url).json() == report
    with engine.connect() as conn:
        assert {
            r.horizon_days: r.snapshot_id
            for r in conn.execute(
                select(suggestion_tracking).where(
                    suggestion_tracking.c.suggestion_id == loop.suggestion.id
                )
            )
        } == before
        assert (
            conn.execute(
                select(daily_reports.c.body).where(daily_reports.c.id == stored.id)
            ).scalar_one()
            == original_body
        )
    settings_url = "/api/v1/risk-controls"
    original = client.get(settings_url).json()
    assert len(original) == 6 and len({r["control"] for r in original}) == 6
    valid = {k: original[1][k] for k in ["control", "enabled", "params"]}
    valid["params"] = {"single_position_max_pct": "25"}
    saved = client.put(settings_url, json=[valid])
    assert saved.status_code == 200
    own = client.get(settings_url).json()
    assert own[1]["params"]["single_position_max_pct"] == "25"
    assert own[1]["default"] == original[1]["default"]
    assert stranger.get(settings_url).json()[1]["params"] == original[1]["default"]
    invalid = {**valid, "params": {"single_position_max_pct": "51"}}
    denied = client.put(settings_url, json=[valid, invalid])
    assert denied.status_code == 400  # duplicate control precedence, atomic rejection
    assert client.get(settings_url).json() == own
    denied = client.put(settings_url, json=[invalid])
    assert denied.status_code == 422
    assert denied.json()["error"]["code"] == "RISK_CONTROL_INVALID_PARAMS"
    assert client.get(settings_url).json() == own
    restore = {
        "control": valid["control"],
        "enabled": True,
        "params": original[1]["default"],
    }
    assert client.put(settings_url, json=[restore]).status_code == 200
    (artifacts() / "backend-assertions.json").write_text(
        json.dumps(
            {
                "real_import_confirm": True,
                "real_analysis_handler": ANALYZE,
                "real_queue_workers": [REPORT, TRACK],
                "report_stock_count": len(report["stocks"]),
                "resolved_evidence_count": len(evidence),
                "tracking_observations": len(data["results"]),
                "foreign_404": True,
                "simulating_draft_rejected": simulation_protection,
                "missing_source_candidate_not_created": True,
                "replay_immutable": True,
                "contract_violations": violations,
            },
            indent=2,
        )
    )

    assert not violations, violations


@pytest.mark.parametrize("row", INPUTS, ids=[r["label"] for r in INPUTS])
def test_synthetic_fixture_schema_only(row):
    """24 reviewed synthetic schema inputs; not an engine/PIT acceptance claim."""
    known = row["state"] in {"present", "stale"}
    payload = {
        "dimension": row["dimension"],
        "facts": [
            {
                "text": row["label"] + "=" + row["operand"],
                "expr": None,
                "evidence_ids": [],
            }
        ]
        if known
        else [],
        "feature_refs": [
            {
                "feature_key": dim.GROUPS[row["dimension"]][0],
                "status": None,
                "evidence_ids": [],
            }
        ],
        "data_status": "stale"
        if row["state"] == "stale"
        else "partial"
        if known
        else "unavailable",
        "data_as_of": "2026-10-28T15:00:00+08:00" if known else None,
        "gaps": [
            {
                "key": row["dimension"],
                "reason": "no_source",
                "message": "TEST纯合成schema输入，不是规则结论",
            }
        ],
    }
    value = DailyDimensionAnalysis.model_validate(payload)
    assert value.model_dump(mode="json") == payload
    assert value.feature_refs[0].status is None
    assert row["label"] == "TEST-" + row["dimension"] + "-" + row["state"]


class SecondSliceSkeleton:
    """Not a pytest Test class: no skip/xfail or pretend second-slice coverage."""

    fixture_inputs = Path(__file__).parent / "fixtures/p2n10_second_slice.json"

    @staticmethod
    def test_intraday_plan_explanation_loop():
        raise NotImplementedError(
            "P2N-10b requires frozen P2N-06..09 and matching real frontend delivery"
        )


def test_daily_risk_tracking_desktop(loop):
    """Invoke only the new local-framework desktop path against the same workers' DB."""
    import uvicorn

    engine, client, stranger, owner, _, settings = loop.env
    root = artifacts()
    origin = "http://127.0.0.1:15580"
    api_settings = settings.model_copy(update={"site_origins": [origin]})
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(api_settings),
            host="127.0.0.1",
            port=18580,
            access_log=False,
            log_config=None,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    frontend = None
    result = None

    def cookies(test_client):
        return [
            {
                "name": c.name,
                "value": c.value,
                "url": origin,
                "httpOnly": "HttpOnly" in c._rest,
                "sameSite": "Lax",
            }
            for c in test_client.cookies.jar
        ]

    # Ephemeral synthetic sessions only; never persisted, printed, or attached.
    context = {
        "ownerCookies": cookies(client),
        "strangerCookies": cookies(stranger),
        "ownerCsrf": client.headers["X-CSRF-Token"],
        "date": str(daily.DATE),
        "suggestionId": str(loop.suggestion.id),
        "simulatedId": str(loop.simulated.id),
        "missingInstanceId": loop.missing,
        "expectedObservations": 3 * len(loop.suggestion.strategies),
        "accountId": str(loop.account),
    }
    child_env = {
        k: os.environ[k] for k in ["PATH", "HOME", "LANG", "LC_ALL", "PLAYWRIGHT_BROWSERS_PATH", "CI", "COREPACK_ENABLE_NETWORK"] if k in os.environ
    }
    child_env.update(
        P2N10_ARTIFACTS=str(root),
        P2N10_REPO=str(ROOT),
        P2N10_BASE_URL=origin,
        P2N10_CONTEXT=json.dumps(context),
        VITE_USE_MOCK="false",
        VITE_API_PROXY="http://127.0.0.1:18580",
        NODE_OPTIONS="--require=" + str(ROOT / "tests/e2e/p2n10-deny-network.cjs"),
        NO_PROXY="127.0.0.1,localhost",
    )
    try:
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "Own API failed to start"
        with (root / "frontend.log").open("w") as frontlog:
            frontend = subprocess.Popen(
                ["node", str(ROOT / "tests/e2e/p2n10-vite.mjs")],
                cwd=ROOT,
                env=child_env,
                stdout=frontlog,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            import urllib.request

            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                assert frontend.poll() is None, (
                    "Own frontend failed to start; see frontend.log"
                )
                try:
                    with urllib.request.urlopen(
                        origin + "/api/v1/health/live", timeout=1
                    ) as response:
                        if response.status == 200:
                            break
                except (OSError, TimeoutError):
                    time.sleep(0.2)
            else:
                raise AssertionError("Own frontend/API readiness timed out")
            command_line = [
                "node",
                str(ROOT / "node_modules/playwright/cli.js"),
                "test",
                "--config",
                "tests/e2e/p2n10-playwright.config.ts",
                "--grep",
                "first-slice",
            ]
            (root / "playwright-command.json").write_text(json.dumps(command_line))
            with (root / "desktop.log").open("w") as desktop_log:
                result = subprocess.run(
                    command_line,
                    check=False,
                    cwd=ROOT,
                    env=child_env,
                    stdout=desktop_log,
                    stderr=subprocess.STDOUT,
                    timeout=150,
                )
    finally:
        if frontend is not None:
            frontend.terminate()
            try:
                frontend.wait(timeout=15)
            except subprocess.TimeoutExpired:
                frontend.kill()
                frontend.wait()
        server.should_exit = True
        thread.join(timeout=15)
        assert not thread.is_alive(), "Own API thread did not stop"
    assert result is not None and result.returncode == 0, (
        "Local desktop path failed; see desktop.log"
    )
    assert json.loads((root / "browser-proxy-denials.json").read_text()) == []
    with engine.connect() as conn:
        assert count(conn, plan_drafts, owner) == 0
