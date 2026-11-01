"""scripts/ci 自测的公共工具。所有“命中”用例在运行时拼接生成，仓库里不存放可被扫描命中的字面量。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CI_DIR = Path(__file__).resolve().parents[1]
REPO = CI_DIR.parents[1]
sys.path.insert(0, str(CI_DIR))


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "ci", "GIT_AUTHOR_EMAIL": "ci@example.invalid",
           "GIT_COMMITTER_NAME": "ci", "GIT_COMMITTER_EMAIL": "ci@example.invalid"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    shutil.copy(REPO / ".secretscan-allow.yaml", repo / ".secretscan-allow.yaml")
    shutil.copy(REPO / ".gitleaks.toml", repo / ".gitleaks.toml")
    return repo


def write(repo: Path, rel: str, content: str | bytes) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_bytes(content)
    return p


def commit_all(repo: Path, msg: str = "c") -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD").strip()


def gitleaks_bin() -> str | None:
    return os.environ.get("GITLEAKS_BIN") or shutil.which("gitleaks")
