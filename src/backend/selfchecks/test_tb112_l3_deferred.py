# ruff: noqa: S101
"""T-B112 L-3: at 仍用调用方时钟（本单不硬改；见报告最小改法）。"""

from __future__ import annotations

import inspect

from app.ingest import ip_limit as ipl


def test_tb112_l3_write_event_still_takes_caller_at() -> None:
    """Documented deferral: _write_event keeps explicit ``at`` parameter."""
    sig = inspect.signature(ipl._write_event)
    assert "at" in sig.parameters
