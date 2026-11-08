"""回放示例（T-T01）：验证回放工具与合成 tape；业务回放（T-T 系列）在此基础上扩展。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from replay_kit import LICENCE_LIKE, FakeClock, ReplayClient, Tape, UnrecordedRequest  # noqa: E402

FIXTURES = HERE.parent / "fixtures"
SCENARIOS = sorted((HERE / "scenarios").glob("*/scenario.json"))
ENDPOINT = "/hsrl/ssjy/all/***"

pytestmark = pytest.mark.replay


def _load(scenario_path: Path) -> tuple[dict, Tape]:
    sc = json.loads(scenario_path.read_text(encoding="utf-8"))
    return sc, Tape.load(FIXTURES / sc["tape"])


def test_tapes_contain_no_licence() -> None:
    tapes = sorted((FIXTURES / "mairui").rglob("*.jsonl"))
    assert tapes
    for tape in tapes:
        text = tape.read_text(encoding="utf-8")
        assert not LICENCE_LIKE.search(text), tape.name
        for line in text.splitlines():
            if line.strip():
                assert json.loads(line).get("_synthetic") is True or "_synthetic" not in tape.parent.name


def test_tape_loader_rejects_licence_like_path(tmp_path: Path) -> None:
    bad = tmp_path / "tape.jsonl"
    bad.write_text(
        '{"t": "2026-11-02T09:30:00+08:00", "endpoint": "/hsrl/ssjy/all/' + "0" * 32
        + '", "params": {}, "status": 200, "body": []}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="licence"):
        Tape.load(bad)


@pytest.mark.parametrize("scenario_path", SCENARIOS, ids=[p.parent.name for p in SCENARIOS])
def test_scenario_replay(scenario_path: Path) -> None:
    sc, tape = _load(scenario_path)
    start = datetime.fromisoformat(sc["clock"]["start"])
    end = datetime.fromisoformat(sc["clock"]["end"])
    step = sc["clock"]["step_seconds"]
    interval = timedelta(seconds=sc["expect"]["refresh_interval_seconds"])
    clock = FakeClock(start)
    client = ReplayClient(tape, clock)

    last_good: datetime | None = None
    last_price: dict[str, str] = {}
    seen_429: set[datetime] = set()
    stale_at: list[str] = []
    while clock.now() <= end:
        frame = client.get(ENDPOINT)
        if frame.status == 200:
            last_good = frame.t
            last_price = {row["dm"]: row["p"] for row in frame.body}
        elif frame.status == 429:
            seen_429.add(frame.t)
        # 陈旧判定（plan 0A.3）：超过刷新间隔 × 2 未更新
        if last_good is None or clock.now() - last_good > 2 * interval:
            stale_at.append(clock.now().isoformat())
        clock.advance(step)

    assert len(seen_429) == sc["expect"]["http_429_count"]
    assert stale_at == sc["expect"]["stale_at"]
    assert last_price == sc["expect"]["last_price"]
    assert len(client.calls) == int((end - start).total_seconds() // step) + 1


def test_request_before_first_frame_is_unrecorded() -> None:
    _, tape = _load(SCENARIOS[0])
    clock = FakeClock(tape.frames[0].t - timedelta(seconds=1))
    with pytest.raises(UnrecordedRequest):
        ReplayClient(tape, clock).get(ENDPOINT)


def test_fake_clock_requires_tz() -> None:
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 11, 2, 9, 30))
