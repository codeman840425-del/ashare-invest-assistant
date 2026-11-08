"""T-T22：每用户麦蕊证书的限速、公平与降级（契约 v0.2.6 §9、plan 2.1B）——参考模型 + 回放模式。

- 参考模型见 ``dl_ref_model.py``（纯标准库）；上游一律是脚本化的合成响应（回放模式），时间用 ``FakeClock``；
  不联网、不出现任何证书值（模型里只有虚构的 licence_id）。
- 本文件的参考模型用例应当通过；后端实现（T-B04a 扩展：每证书令牌桶/队列/DRR、熔断与状态机、verify_licence、
  source_licence_id）落地后，用 ``test_backend_*`` 用例以同一组场景对照。后端尚无对应模块 → xfail(strict=False)，原因写明责任人。
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dl_ref_model import (  # noqa: E402
    BJ, TIER_PER_MINUTE, LicenceState, RefIngest, RefScheduler, SlidingWindowLimiter, manual_refresh, next_quota_resume,
    user_data_block,
)
from replay_kit import FakeClock  # noqa: E402

pytestmark = pytest.mark.replay

B04A = ("后端 T-B04a 扩展（T-A07 §5：每证书令牌桶/队列/DRR、熔断与状态机、verify_licence、source_licence_id；"
        "后端尚无对应实现，见 plan 2.1B-2/2.1B-6）")
START = datetime(2026, 11, 2, 9, 30, tzinfo=BJ)
BACKEND_DIR = Path(os.environ.get("AIA_BACKEND_DIR", HERE.parents[1] / "src" / "backend")).resolve()


def _states(**tiers: str) -> dict[str, LicenceState]:
    return {lid: LicenceState(licence_id=lid, tier=t, status="active") for lid, t in tiers.items()}


# ======================= 组 2：限速按证书 =======================
@pytest.mark.parametrize(("tier", "limit"), sorted(TIER_PER_MINUTE.items()))
def test_tier_defaults_are_half_of_official(tier, limit):
    """plan 2.1B-2：默认取官方频率的一半（钻石 6000→3000、包年 3000→1500、包月/体验 1000→500、免费/其他 300→150）。"""
    official = {"diamond": 6000, "annual": 3000, "monthly": 1000, "trial": 1000, "free": 300, "other": 300}
    assert limit * 2 == official[tier]


def test_sliding_window_never_exceeds_limit():
    clock = FakeClock(START)
    lim = SlidingWindowLimiter(150)
    times = []
    for _ in range(3000):
        if lim.allow(clock.now()):
            lim.take(clock.now())
            times.append(clock.now())
        clock.advance(0.05)
    assert times
    for i, t in enumerate(times):
        assert sum(1 for u in times[i:] if u < t + timedelta(seconds=60)) <= 150


def test_rate_limit_is_per_licence_not_global():
    """A（免费 150/分钟）耗尽后，B（钻石）仍可调度；每证书 60 秒内调用数 ≤ 各自上限。"""
    clock = FakeClock(START)
    sch = RefScheduler(clock, _states(A="free", B="diamond"), global_concurrency=2)
    for _ in range(1000):
        sch.submit("A", "p1")
        sch.submit("B", "p1")
    for _ in range(1200):  # 60 秒内每 50ms 调度一轮
        for _ in range(2):
            job = sch.next()
            if job:
                sch.complete(job)
        clock.advance(0.05)
    by = {lid: [t for t, j in sch.dispatched if j.licence_id == lid] for lid in ("A", "B")}
    assert len(by["A"]) == TIER_PER_MINUTE["free"]
    assert len(by["B"]) > len(by["A"]) * 3
    for lid, ts in by.items():
        lim = TIER_PER_MINUTE[sch.states[lid].tier]
        for i, t in enumerate(ts):
            assert sum(1 for u in ts[i:] if u < t + timedelta(seconds=60)) <= lim, lid


def test_admin_override_limit_applies_to_that_licence_only():
    clock = FakeClock(START)
    sch = RefScheduler(clock, _states(A="diamond", B="diamond"), limits={"A": 10})
    for _ in range(50):
        sch.submit("A", "p1")
        sch.submit("B", "p1")
    for _ in range(100):
        job = sch.next()
        if job:
            sch.complete(job)
    assert sum(j.licence_id == "A" for _, j in sch.dispatched) == 10
    assert sum(j.licence_id == "B" for _, j in sch.dispatched) == 50


def test_p0_of_other_licence_goes_next_round_despite_backlog():
    """§9：A 积压 10,000 个 P1、B 有 1 个 P0 → B 的 P0 在下一个调度轮发出。"""
    clock = FakeClock(START)
    sch = RefScheduler(clock, _states(A="diamond", B="free"))
    for _ in range(10_000):
        sch.submit("A", "p1")
    first = sch.next()
    sch.complete(first)
    sch.submit("B", "p0")
    job = sch.next()
    assert (job.licence_id, job.priority) == ("B", "p0")


def test_same_priority_alternates_between_licences():
    """§9：A、B 各有 P1 时交替发出（DRR，quantum = 1 次调用）。"""
    clock = FakeClock(START)
    sch = RefScheduler(clock, _states(A="diamond", B="diamond"))
    for _ in range(20):
        sch.submit("A", "p1")
    for _ in range(5):
        sch.submit("B", "p1")
    order = []
    for _ in range(25):
        job = sch.next()
        sch.complete(job)
        order.append(job.licence_id)
    assert order[:10] == ["A", "B"] * 5
    assert order[10:] == ["A"] * 15


def test_concurrency_per_licence_1_global_2():
    clock = FakeClock(START)
    sch = RefScheduler(clock, _states(A="diamond", B="diamond", C="diamond"))
    for lid in "ABC":
        for _ in range(3):
            sch.submit(lid, "p1")
    a, b = sch.next(), sch.next()
    assert a.licence_id != b.licence_id
    assert sch.next() is None  # 全局并发 2
    sch.complete(a)
    c = sch.next()
    assert c.licence_id not in {b.licence_id}  # 每证书并发 1：b 未完成前其证书不再出队


# ======================= 组 3：证书无效/过期时的降级 =======================
def test_102_invalid_stops_that_licence_only():
    """§9 回放：上游 102 → invalid，之后该证书外呼 0 次，其他证书不受影响；通知 data_licence。"""
    clock = FakeClock(START)
    st = _states(A="annual", B="annual")
    script = {"A": iter(["ok"] * 100), "B": iter(["102"] + ["ok"] * 100)}
    ing = RefIngest(clock, st, {"ua": "A", "ub": "B"}, lambda lid, ep: next(script[lid]))
    assert ing.fetch_for("ub", "/hsrl/ssjy") == "102"
    assert st["B"].status == "invalid" and st["B"].notifications == [{"kind": "data_licence", "status": "invalid"}]
    before = len(ing.calls)
    for _ in range(10):
        clock.advance(600)
        assert ing.fetch_for("ub", "/hsrl/ssjy") == "data_licence_unavailable"
        assert ing.fetch_for("ua", "/hsrl/ssjy") == "ok"
    assert [c for c in ing.calls[before:] if c[1] == "B"] == []
    assert st["A"].status == "active"


def test_102_recovers_only_after_user_reset():
    clock = FakeClock(START)
    s = LicenceState("B", tier="annual", status="active")
    s.on_upstream("102", clock.now())
    clock.advance(86400 * 3)
    assert not s.can_call(clock.now())
    s.user_reset()  # 用户重新 PUT 或点“测试”
    assert s.status == "pending_verification" and s.can_call(clock.now())


@pytest.mark.parametrize("at", ["09:30", "23:59", "00:00"])
def test_101_quota_exceeded_until_next_day_0001_bj(at):
    h, m = map(int, at.split(":"))
    now = START.replace(hour=h, minute=m)
    s = LicenceState("A", tier="monthly", status="active")
    s.on_upstream("101", now)
    want = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=BJ).replace(minute=1)
    assert s.status == "quota_exceeded" and s.paused_until == want == next_quota_resume(now)
    assert not s.can_call(want - timedelta(seconds=1)) and s.can_call(want)


def test_103_ip_limited_pause_120s_and_escalate_on_third_within_hour():
    clock = FakeClock(START)
    s = LicenceState("A", tier="annual", status="active")
    for i in range(2):
        s.on_upstream("103", clock.now())
        assert s.status == "ip_limited" and s.paused_until == clock.now() + timedelta(seconds=120)
        assert s.notifications == []
        clock.advance(121)
        assert s.can_call(clock.now())
    s.on_upstream("429", clock.now())  # HTTP 429 与 103 同等处理；1 小时内第 3 次
    assert s.paused_until == clock.now() + timedelta(seconds=3600)
    assert s.notifications == [{"kind": "data_licence", "status": "ip_limited"}]


def test_103_hits_outside_one_hour_do_not_escalate():
    clock = FakeClock(START)
    s = LicenceState("A", tier="annual", status="active")
    for _ in range(3):
        s.on_upstream("103", clock.now())
        clock.advance(1900)
    assert s.paused_until - (clock.now() - timedelta(seconds=1900)) == timedelta(seconds=120)
    assert s.notifications == []


@pytest.mark.parametrize("signal", ["503_rate", "network", "http_5xx"])
def test_rate_503_backoff_then_breaker_after_5(signal):
    """频率 503 / 网络错误 / 5xx：状态不变，退避 1→2→4→8 秒；连续 5 次 → 熔断 300 秒（paused_until）。"""
    clock = FakeClock(START)
    s = LicenceState("A", tier="annual", status="active")
    for wait in (1, 2, 4, 8):
        s.on_upstream(signal, clock.now())
        assert s.status == "active" and s.paused_until == clock.now() + timedelta(seconds=wait)
        clock.advance(wait)
    s.on_upstream(signal, clock.now())
    assert s.status == "active" and s.paused_until == clock.now() + timedelta(seconds=300)
    s.on_upstream("ok", clock.now() + timedelta(seconds=300))
    assert s.consecutive_failures == 0


def test_backoff_caps_at_60s():
    from dl_ref_model import BACKOFF_S  # noqa: PLC0415

    assert BACKOFF_S[-1] == 60 and list(BACKOFF_S) == sorted(BACKOFF_S)


def test_data_missing_503_does_not_trip_breaker():
    clock = FakeClock(START)
    s = LicenceState("A", tier="annual", status="active")
    for _ in range(10):
        s.on_upstream("503_missing", clock.now())
    assert s.status == "active" and s.paused_until is None and s.consecutive_failures == 0
    assert s.can_call(clock.now())


@pytest.mark.parametrize(("tier", "p0_ok"), [("diamond", True), ("annual", False), ("monthly", False), ("free", False)])
def test_expired_diamond_keeps_p0_only_others_stop(tier, p0_ok):
    now = START
    s = LicenceState("A", tier=tier, status="active", expires_on=date(2026, 11, 1))
    assert s.can_call(now, "p0") is p0_ok
    assert not s.can_call(now, "p1") and not s.can_call(now, "p2")
    assert s.status == "expired" and s.notifications == [{"kind": "data_licence", "status": "expired"}]


def test_not_yet_expired_on_expiry_day():
    s = LicenceState("A", tier="annual", status="active", expires_on=START.date())
    assert s.can_call(START, "p1") and s.status == "active"


def test_admin_pause_stops_until_resume():
    s = LicenceState("A", tier="annual", status="active")
    s.admin_pause()
    assert not s.can_call(START, "p0")
    s.admin_resume()
    assert s.status == "pending_verification" and s.can_call(START, "p0")


@pytest.mark.parametrize("status", ["invalid", "expired", "quota_exceeded", "ip_limited", "paused_by_admin", "not_set"])
@pytest.mark.parametrize("has_cached", [True, False])
def test_user_view_when_licence_unusable(status, has_cached):
    """§9：证书不可用时读接口 ``data_status ∈ {stale, unavailable}``、gaps 含 data_licence_unavailable；
    manual_refresh → 409 DATA_LICENCE_UNAVAILABLE（details.status = 当前状态）。"""
    s = LicenceState("B", tier="annual", status=status, paused_until=START + timedelta(hours=1))
    if status == "expired":
        s.expires_on = date(2026, 11, 1)
    blk = user_data_block(s, START, has_cached)
    assert blk["data_status"] == ("stale" if has_cached else "unavailable")
    assert {g["reason"] for g in blk["gaps"]} == {"data_licence_unavailable"}
    code, body = manual_refresh(s, START)
    assert (code, body["code"], body["details"]["status"]) == (409, "DATA_LICENCE_UNAVAILABLE", status)


def test_no_cross_licence_fallback_for_user_b():
    """§9：B 证书 invalid 时，ingest 没有用 A 或管理员的证书为 B 发出任何请求。"""
    clock = FakeClock(START)
    st = _states(A="diamond", ADMIN="diamond", B="annual")
    st["B"].status = "invalid"
    ing = RefIngest(clock, st, {"ua": "A", "uadmin": "ADMIN", "ub": "B"}, lambda lid, ep: "ok")
    for ep in ("/hsrl/ssjy", "/hszbl/fsjy", "/hscp/gsjj"):
        assert ing.fetch_for("ub", ep) == "data_licence_unavailable"
        ing.fetch_for("ua", ep)
    assert [c for c in ing.calls if c[0] == "ub"] == []
    assert all(c[1] == {"ua": "A", "uadmin": "ADMIN"}[c[0]] for c in ing.calls)


def test_per_licence_rows_carry_own_source_licence_id():
    """§9：per_licence 模式下 A 读到的所有行情行 source_licence_id 都是 A 的证书。"""
    clock = FakeClock(START)
    st = _states(A="diamond", B="annual")
    ing = RefIngest(clock, st, {"ua": "A", "ub": "B"}, lambda lid, ep: "ok")
    for ep in ("/hsrl/ssjy", "/hszbl/fsjy"):
        ing.fetch_for("ua", ep)
        ing.fetch_for("ub", ep)
    assert ing.rows_visible_to("ua") and {r["source_licence_id"] for r in ing.rows_visible_to("ua")} == {"A"}
    assert {r["source_licence_id"] for r in ing.rows_visible_to("ub")} == {"B"}


# ======================= 后端对照（T-B04a 扩展） =======================
def _backend_module(*names: str):
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    for name in names:
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    return None


#: 后端可能的模块名（plan 2.2 ingest；以实现为准，落地后在此登记）
SCHEDULER_MODULES = ("app.ingest.licences", "app.ingest.scheduler", "app.workers.ingest_scheduler", "app.ingest.licence_scheduler")


@pytest.mark.xfail(strict=False, reason=B04A)
def test_backend_has_per_licence_scheduler_and_state_machine():
    """后端须有每证书调度（令牌桶/队列/DRR）与降级状态机；落地后把参考模型场景换成后端实现对照。"""
    mod = _backend_module(*SCHEDULER_MODULES)
    assert mod is not None, f"后端未找到 {SCHEDULER_MODULES} 之一"
    names = set(dir(mod))
    assert names & {"LicenceScheduler", "PerLicenceScheduler"} and names & {"LicenceState", "LicenceStateMachine"}


def test_reference_model_constants_match_plan_snapshot():
    """参考模型的常量与 plan v0.2.6 §6.1 ``ingest.yaml`` 快照（tests/backend/api_app/config_defaults）一致。"""
    import yaml  # noqa: PLC0415

    import dl_ref_model as m  # noqa: PLC0415

    snap = yaml.safe_load((HERE.parents[0] / "backend" / "api_app" / "config_defaults" / "ingest.yaml").read_text(encoding="utf-8"))
    lic = snap["licences"]
    assert m.TIER_PER_MINUTE == lic["tier_per_minute"]
    assert list(m.BACKOFF_S) == lic["breaker"]["backoff_s"]
    assert (m.BREAKER_CONSECUTIVE_503, m.BREAKER_OPEN_S) == (lic["breaker"]["consecutive_503"], lic["breaker"]["open_s"])
    assert m.IP_LIMITED_PAUSE_S == lic["ip_limited_pause_s"]
    assert m.IP_LIMITED_ESCALATE == lic["ip_limited_escalate"]
    assert m.DIAMOND_AFTER_EXPIRY_PER_DAY == lic["diamond_after_expiry_per_day"]
    assert m.QUOTA_RESUME_AT.strftime("%H:%M") == lic["quota_resume_at"]
    assert snap["data_sharing"]["allow_cross_licence_fallback"] is False
