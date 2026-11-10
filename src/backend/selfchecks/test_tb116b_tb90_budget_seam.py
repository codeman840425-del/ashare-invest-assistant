# ruff: noqa: S101
"""T-B116b: tb90 judgment — selfcheck opens daily.live_budget_issue; limit unchanged."""

from __future__ import annotations

from pathlib import Path

from app.master import daily_delivery as daily

ROOT = Path(__file__).resolve().parents[3]


def test_tb116b_daily_http_limit_unchanged() -> None:
    assert daily.DAILY_HTTP_LIMIT == 1
    assert len(daily.LISTS) == 3
    assert daily.live_budget_issue() == "daily_http_budget_unresolved"


def test_tb116b_tb90_pipeline_patches_daily_and_ingest_budget() -> None:
    src = (ROOT / "src/backend/selfchecks/test_tb90_daily_pipeline.py").read_text(encoding="utf-8")
    assert 'monkeypatch.setattr(daily, "live_budget_issue", lambda: None)' in src
    assert 'monkeypatch.setattr(ingest, "live_budget_issue", lambda: None)' in src
    assert "DAILY_HTTP_LIMIT = 3" not in src
    assert "DAILY_HTTP_LIMIT = len(LISTS)" not in src
