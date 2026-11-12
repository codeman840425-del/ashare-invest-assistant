"""T-B63 pytest：现有主表保护及真实隔离 PG 边界；不是信号流水线验收。

源自 8e8525e；显式运行 pytest tests/backend/integration/test_tb63_signals.py；PG 用例仅连接既有专用 socket，
沿用 tb60 的库名/schema 防误用及最终回滚，不读取环境 DSN 或连接共享库。
"""

from __future__ import annotations

import datetime as dt
import sys
import os
import tempfile
from pathlib import Path
from typing import cast

import pytest

# 后端尚未合入旧测试分支时，显式指向报告已核对的既有离线快照；缺实现直接失败，不跳过。
BACKEND = Path(os.environ.get("AIA_BACKEND_DIR", Path(__file__).resolve().parents[3] / "src/backend"))
sys.path.insert(0, str(BACKEND))
from app.schemas.enums import Action, ReasonCode
from app.signals.admission import MasterAdmission, assess_master
from selfchecks import tb60

from .tb28_isolation import verify_isolated_pg

DAY = dt.date(2026, 11, 6)


def row(
    *, kind: str | None = "stock", status: str | None = "listed", end: dt.date | None = None
) -> dict[str, object]:
    return {"type": kind, "listing_status": status, "delist_date": end}


@pytest.mark.parametrize(
    ("master", "action", "expected"),
    [
        (row(), Action.BUY, MasterAdmission(True)),
        (row(kind="cdr"), Action.SELL, MasterAdmission(True)),
        (None, Action.BUY, MasterAdmission(False, "unknown_security")),
        (None, Action.HOLD, MasterAdmission(False, "no_candidate_action")),
        (None, Action.WAIT, MasterAdmission(False, "no_candidate_action")),
        (row(kind="etf"), Action.BUY, MasterAdmission(False, "not_strategy_eligible")),
        (row(kind="index"), Action.BUY, MasterAdmission(False, "not_strategy_eligible")),
        (row(kind=None), Action.BUY, MasterAdmission(False, "not_strategy_eligible")),
        (row(status="missing_from_list"), Action.BUY, MasterAdmission(False, "missing_from_list")),
        (row(end=DAY), Action.BUY, MasterAdmission(False, "delisted")),
        (row(end=DAY - dt.timedelta(days=1)), Action.SELL, MasterAdmission(False, "delisted")),
        (row(end=DAY + dt.timedelta(days=1)), Action.BUY, MasterAdmission(True)),
        (
            row(status="delisting_period"),
            Action.BUY,
            MasterAdmission(False, "delisting_buy", ReasonCode.ST_OR_DELISTING),
        ),
        (
            row(status="delisting_period"),
            Action.ADD,
            MasterAdmission(False, "delisting_buy", ReasonCode.ST_OR_DELISTING),
        ),
        (row(status="delisting_period"), Action.SELL, MasterAdmission(True)),
        (row(status="delisting_period"), Action.REDUCE, MasterAdmission(True)),
    ],
)
def test_assess_boundaries(
    master: dict[str, object] | None, action: Action, expected: MasterAdmission
) -> None:
    assert assess_master(master, action=action, trade_date=DAY) == expected  # noqa: S101


@pytest.mark.parametrize("action", list(Action))
def test_delisted_never_admits_candidate(action: Action) -> None:
    # HOLD/WAIT 已在更早的动作门禁拒绝；任何动作均不得进入写入器。
    decision = assess_master(
        row(status="delisted", end=DAY + dt.timedelta(days=1)), action=action, trade_date=DAY
    )
    assert not decision.allowed  # noqa: S101


@pytest.mark.parametrize("status", [None, "unknown", "suspended"])
def test_unknown_status_is_not_invented(status: str | None) -> None:
    with pytest.raises(ValueError, match="上市状态未确认"):
        assess_master(row(status=status), action=Action.BUY, trade_date=DAY)


@pytest.mark.parametrize("invalid", [dt.datetime(2026, 11, 6), "2026-11-06", None])
def test_explicit_market_date_required(invalid: object) -> None:
    with pytest.raises(ValueError, match="市场交易日"):
        assess_master(None, action=Action.BUY, trade_date=cast(dt.date, invalid))


def test_invalid_action_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a valid Action"):
        assess_master(row(), action=cast(Action, "invented"), trade_date=DAY)


@pytest.mark.integration
@pytest.mark.local_tb58
@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted",
    reason="Grok 2026-11-12 B1: fixed tb58 identity is local-only; unavailable on GitHub-hosted runners",
)
def test_isolated_pg_guard_writes_and_savepoint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 先核查固定容器身份/none网络/无映射/独立卷，再运行原45项真实PG断言。
    verify_isolated_pg()
    # 复用真实写入/外键/分区夹具，不以 mock 连接或空回调替代；失败不跳过。
    monkeypatch.setattr(
        sys,
        "argv",
        ["tb60.py", "--socket-dir", str(Path(tempfile.gettempdir()) / "tb58-pg3-socket")],
    )
    try:
        result = tb60.main()
    except Exception:
        pytest.fail("隔离PG检查失败；不输出连接参数，先检查本机隔离环境", pytrace=False)
    output = capsys.readouterr().out
    assert result == 0, output  # noqa: S101
    assert "45 passed, 0 failed" in output  # noqa: S101
    assert "所有DDL/合成数据最终回滚" in output  # noqa: S101
