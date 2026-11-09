"""Offline control-entry negatives; no database/network or credentials."""

# ruff: noqa: S101
import os
import sys
from pathlib import Path

import pytest

from app.cli import ingest_control
from app.ingest.send_control import critical
from app.ingest.shared_gate import GateClosedError


@pytest.mark.skipif(
    os.name == "posix", reason="POSIX mutex is exercised in the isolated Linux suite"
)
def test_non_posix_live_control_is_refused(tmp_path: Path) -> None:
    with pytest.raises(GateClosedError, match="requires_POSIX"), critical(tmp_path):
        pytest.fail("non-POSIX dispatch was accepted")
    assert list(tmp_path.iterdir()) == []


def test_operator_cli_without_action_has_no_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAIRUI_SHARED_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["ingest_control"])
    with pytest.raises(SystemExit) as caught:
        ingest_control.main()
    assert caught.value.code == 2
    assert list(tmp_path.iterdir()) == []
