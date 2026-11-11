# ruff: noqa: S101 -- pytest assertions in synthetic gate tests
"""End-to-end gate checks use only temporary synthetic test trees."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).with_name("check_collection.py")


def run_guard(root: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    output = root / "summary.json"
    result = subprocess.run(  # noqa: S603 -- fixed interpreter/script, synthetic argument list; no shell
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--min-collected",
            "1",
            "--output",
            str(output),
            *extra,
        ],
        env={**os.environ, "PYTHONUTF8": "1", "PYTEST_ADDOPTS": "-k impossible_selection"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return result, json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}


def tree(tmp_path: Path, content: str) -> Path:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_synthetic.py").write_text(content, encoding="utf-8")
    return tests


def test_collection_never_runs_test_body_or_fixture(tmp_path: Path) -> None:
    tests = tree(tmp_path, "def test_body():\n    raise RuntimeError('body must not run')\n")
    (tests / "conftest.py").write_text(
        "import pytest\n@pytest.fixture(autouse=True)\ndef fixture():\n"
        "    raise RuntimeError('fixture must not run')\n",
        encoding="utf-8",
    )
    # Neither inherited PYTEST_ADDOPTS nor an ini filter may silently drop items.
    (tests / "pytest.ini").write_text(
        "[pytest]\naddopts = -k another_impossible\n", encoding="utf-8"
    )
    result, summary = run_guard(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert summary["passed"]
    assert summary["collected"] == 1
    assert summary["collection_errors"] == 0
    assert summary["test_bodies_executed"] is False


@pytest.mark.parametrize(
    "failure", ["raise ImportError('synthetic missing dependency')\n", "def broken(:\n"]
)
def test_import_or_syntax_error_fails_even_with_valid_items(tmp_path: Path, failure: str) -> None:
    tests = tree(tmp_path, "def test_good(): pass\n")
    (tests / "test_broken.py").write_text(failure, encoding="utf-8")
    result, summary = run_guard(tmp_path)
    assert result.returncode == 1
    assert summary["collected"] == 1
    assert summary["collection_errors"] == 1
    assert not summary["passed"]


def test_errors_fail_even_if_plugin_overrides_native_exit(tmp_path: Path) -> None:
    tests = tree(tmp_path, "raise ImportError('synthetic missing dependency')\n")
    (tests / "test_good.py").write_text("def test_good(): pass\n", encoding="utf-8")
    (tests / "conftest.py").write_text(
        "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 0\n",
        encoding="utf-8",
    )
    result, summary = run_guard(tmp_path)
    assert summary["pytest_exit_code"] == 0
    assert summary["collection_errors"] == 1
    assert result.returncode == 1
    assert not summary["passed"]


def test_empty_tree_is_failure(tmp_path: Path) -> None:
    tree(tmp_path, "# no tests\n")
    result, summary = run_guard(tmp_path)
    assert result.returncode == 1
    assert summary["collected"] == 0
    assert not summary["passed"]


def test_below_baseline_is_failure(tmp_path: Path) -> None:
    tree(tmp_path, "def test_good(): pass\n")
    result, summary = run_guard(tmp_path, "--min-collected", "2")
    assert result.returncode == 1
    assert not summary["passed"]
    assert summary["pytest_exit_code"] == 0
    assert summary["collected"] == 1


def test_skipped_module_is_reported_separately(tmp_path: Path) -> None:
    tests = tree(tmp_path, "def test_good(): pass\n")
    (tests / "test_optional.py").write_text(
        "import pytest\npytest.importorskip('synthetic_nonexistent_optional_package')\n",
        encoding="utf-8",
    )
    result, summary = run_guard(tmp_path)
    assert result.returncode == 0
    assert summary["passed"]
    assert len(summary["skipped_collectors"]) == 1
    assert summary["collected"] == 1


@pytest.mark.parametrize("extra", [["--min-collected", "0"], ["missing"], ["../outside"]])
def test_invalid_scope_or_threshold_is_usage_error(tmp_path: Path, extra: list[str]) -> None:
    tree(tmp_path, "def test_good(): pass\n")
    result, summary = run_guard(tmp_path, *extra)
    assert result.returncode == 2
    assert summary == {}
