"""check_gateway_limits.py 正反例（T-O03）：nginx client_max_body_size ↔ config/imports.yaml ↔ 413 信封 max_bytes。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import check_gateway_limits as cgl
from conftest import CI_DIR, REPO, write

PLAN_YAML = ("schema_version: 1\nmax_file_bytes: 5242880\nmax_files_per_upload: 5\nmax_request_bytes: 27262976\n"
             "max_rows_per_file: 50000\nallowed_extensions: [\".txt\", \".csv\"]\nraw_file_retention_days: 365\n")


@pytest.fixture
def gw_repo(tmp_path: Path) -> Path:
    """用仓库里真实的 nginx.conf + plan 6.1 的 imports.yaml 取值。"""
    (tmp_path / "deploy/nginx").mkdir(parents=True)
    shutil.copy(REPO / cgl.NGINX_CONF, tmp_path / cgl.NGINX_CONF)
    write(tmp_path, cgl.IMPORTS_YAML, PLAN_YAML)
    return tmp_path


def _sub(repo: Path, rel: str, old: str, new: str) -> None:
    p = repo / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, old
    p.write_text(text.replace(old, new), encoding="utf-8")


def test_repo_nginx_matches_plan_values(gw_repo: Path) -> None:
    assert cgl.check(gw_repo) == []


def test_cli_exit_codes(gw_repo: Path) -> None:
    run = lambda: subprocess.run([sys.executable, str(CI_DIR / "check_gateway_limits.py"), "--repo", str(gw_repo)],  # noqa: E731
                                 capture_output=True, text=True)
    assert run().returncode == 0
    (gw_repo / cgl.IMPORTS_YAML).unlink()
    r = run()
    assert r.returncode == 1 and "config/imports.yaml 不存在" in r.stdout, r.stdout


def test_missing_imports_yaml_is_explicit_error(gw_repo: Path) -> None:
    (gw_repo / cgl.IMPORTS_YAML).unlink()
    errs = cgl.check(gw_repo)
    assert len(errs) == 1 and "不存在" in errs[0]


@pytest.mark.parametrize("old,new,needle", [
    ("client_max_body_size 26m;", "client_max_body_size 25m;", "不大于"),        # = 应用上限，不是“略大于”
    ("client_max_body_size 26m;", "client_max_body_size 27m;", "≠ imports.max_request_bytes"),
    ('"max_bytes":27262976', '"max_bytes":26214400', "413 信封"),
])
def test_nginx_mismatch(gw_repo: Path, old: str, new: str, needle: str) -> None:
    _sub(gw_repo, cgl.NGINX_CONF, old, new)
    errs = cgl.check(gw_repo)
    assert any(needle in e for e in errs), errs


@pytest.mark.parametrize("old,new,needle", [
    ("max_request_bytes: 27262976", "max_request_bytes: 26214400", "≠ imports.max_request_bytes"),
    ("max_file_bytes: 5242880", "max_file_bytes: 6291456", "不大于"),                    # 6 MiB × 5 > 26m
    ("max_files_per_upload: 5", "max_files_per_upload: \"5\"", "不是正整数"),
    ("max_file_bytes: 5242880\n", "", "max_file_bytes 缺失"),
])
def test_imports_yaml_mismatch(gw_repo: Path, old: str, new: str, needle: str) -> None:
    _sub(gw_repo, cgl.IMPORTS_YAML, old, new)
    errs = cgl.check(gw_repo)
    assert any(needle in e for e in errs), errs


def test_units_and_nested_imports_key(gw_repo: Path) -> None:
    _sub(gw_repo, cgl.NGINX_CONF, "client_max_body_size 26m;", "client_max_body_size 26624k;")
    write(gw_repo, cgl.IMPORTS_YAML, "imports:\n" + "".join("  " + ln + "\n" for ln in PLAN_YAML.splitlines()))
    assert cgl.check(gw_repo) == []


def test_commented_directive_ignored_and_conflicting_values(gw_repo: Path) -> None:
    _sub(gw_repo, cgl.NGINX_CONF, "client_max_body_size 26m;", "# client_max_body_size 1m;\n  client_max_body_size 26m;")
    assert cgl.check(gw_repo) == []
    _sub(gw_repo, cgl.NGINX_CONF, "listen 80;", "listen 80;\n    client_max_body_size 1m;")
    assert any("多个不同取值" in e for e in cgl.check(gw_repo))
