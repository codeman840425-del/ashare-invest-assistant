"""T-O09a：check_ignored_sources.py 正反例 + 本仓库 .gitignore 不误伤源码、仍挡住私钥/证书文件。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import CI_DIR, REPO, git, write

SCRIPT = CI_DIR / "check_ignored_sources.py"


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(SCRIPT), "--repo", str(repo), *args], capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    return r


def commit(repo: Path, files: dict[str, str], gitignore: str) -> None:
    write(repo, ".gitignore", gitignore)
    for k, v in files.items():
        write(repo, k, v)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "t")


TS_IMPORTER = {"src/frontend/src/mocks/session.ts": "import { a } from './licence';\nexport const b = a;\n"}


def test_import_of_ignored_ts_file_fails(repo: Path) -> None:
    commit(repo, TS_IMPORTER, "licence.*\n")
    write(repo, "src/frontend/src/mocks/licence.ts", "export const a = 1;\n")  # 本地有，提交里没有
    r = run(repo)
    assert r.returncode == 1, r.stdout
    assert "imports  src/frontend/src/mocks/session.ts" in r.stdout and "licence.ts" in r.stdout
    assert "canary" in r.stdout  # 宽规则本身也被探针抓到


def test_import_of_ignored_python_module_fails(repo: Path) -> None:
    commit(repo, {"src/backend/app/__init__.py": "", "src/backend/app/svc.py": "from app.imports import parse\n"},
           "imports/\n")
    r = run(repo)
    assert r.returncode == 1, r.stdout
    assert "src/backend/app/imports" in r.stdout


def test_relative_python_import_of_ignored_file_fails(repo: Path) -> None:
    commit(repo, {"src/backend/app/__init__.py": "", "src/backend/app/svc.py": "from .secret_store import x\n"},
           "*secret*.py\n!src/backend/app/svc.py\n")
    r = run(repo)
    assert r.returncode == 1, r.stdout
    assert "secret_store.py" in r.stdout


def test_tracked_source_matched_by_rule_fails(repo: Path) -> None:
    commit(repo, {"tests/unit/test_keys.py": "x = 1\n"}, "")
    write(repo, ".gitignore", "*keys*\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "wide rule")
    r = run(repo)
    assert r.returncode == 1, r.stdout
    assert "tracked  tests/unit/test_keys.py" in r.stdout


def test_worktree_flag_reports_untracked_ignored_source(repo: Path) -> None:
    commit(repo, {"src/a.ts": "export {};\n"}, "/src/gen/\n")
    write(repo, "src/gen/b.ts", "export {};\n")
    assert run(repo).returncode == 0
    r = run(repo, "--worktree")
    assert r.returncode == 1 and "worktree src/gen/b.ts" in r.stdout


def test_narrow_rules_pass(repo: Path) -> None:
    files = {**TS_IMPORTER, "src/frontend/src/mocks/licence.ts": "export const a = 1;\n",
             "src/backend/app/__init__.py": "", "src/backend/app/svc.py": "import secrets\nfrom app import x\n",
             "src/backend/app/x.py": "", "src/frontend/src/missing.ts": "import './nope';\n"}
    commit(repo, files, "/secrets/\ndeploy/secrets/\n*.pem\n*.key\n*.lic\nnode_modules/\n")
    r = run(repo)
    assert r.returncode == 0, r.stdout  # stdlib secrets 不算；缺失但未被忽略的引用交给 tsc


def test_directory_rule_only_warns(repo: Path) -> None:
    commit(repo, {"src/a.py": "x = 1\n"}, "data/\n")
    r = run(repo)
    assert r.returncode == 0, r.stdout
    assert "::warning" in r.stdout and "data/" in r.stdout


def test_this_repo_passes() -> None:
    r = run(REPO)
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("path", ["src/frontend/src/mocks/licence.ts", "src/backend/app/licences/keys.py",
                                  "src/frontend/src/api/licenceQueries.ts", "src/backend/app/licence.py",
                                  "tests/backend/test_licence.py", "src/backend/app/secrets.py"])
def test_repo_gitignore_does_not_ignore_sources(path: str) -> None:
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "--no-index", "-q", path])
    assert r.returncode == 1, f"{path} 被 .gitignore 忽略了"


@pytest.mark.parametrize("path", ["deploy/secrets/x", "secrets/x", "a/data_licence_seal_private_keys",
                                  "a/data_licence_seal_public_keys", "tls/server.key", "tls/server.pem",
                                  "c/client.p12", "u/mairui.lic", "x/id_ed25519", "deploy/env/.env"])
def test_repo_gitignore_still_ignores_key_files(path: str) -> None:
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "--no-index", "-q", path])
    assert r.returncode == 0, f"{path} 应被 .gitignore 忽略"


def test_clean_check_uses_committed_content_and_leaves_worktree_alone(repo: Path) -> None:
    """clean_check.sh 只看提交：本地未提交/被忽略的文件不影响结果，也不会被删。"""
    import shutil
    (repo / "scripts/ci").mkdir(parents=True)
    for name in ("clean_check.sh", "check_ignored_sources.py"):
        shutil.copy(CI_DIR / name, repo / "scripts/ci" / name)
    (repo / ".github/workflows").mkdir(parents=True)
    for wf in ("ci.yml", "secret-scan.yml"):
        shutil.copy(REPO / ".github/workflows" / wf, repo / ".github/workflows" / wf)
    commit(repo, TS_IMPORTER, "licence.*\n")
    write(repo, "src/frontend/src/mocks/licence.ts", "export const a = 1;\n")  # 本地有、被忽略
    write(repo, "notes.txt", "uncommitted\n")
    r = subprocess.run(["bash", "scripts/ci/clean_check.sh", "ignored-sources"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 1 and "FAIL  ignored-sources" in r.stdout, r.stdout + r.stderr
    assert (repo / "src/frontend/src/mocks/licence.ts").exists() and (repo / "notes.txt").exists()
    assert "clean-check" not in git(repo, "worktree", "list")
    write(repo, ".gitignore", "*.key\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fix")
    r = subprocess.run(["bash", "scripts/ci/clean_check.sh", "ignored-sources"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0 and "ok    ignored-sources" in r.stdout, r.stdout + r.stderr
