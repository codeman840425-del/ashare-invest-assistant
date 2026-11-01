"""T-O03：secret_scan.py 及复用它的脚本只依赖 pyyaml，且各处固定为同一版本，没有隐含依赖。

覆盖：两个 workflow 的 PYYAML_VERSION、.pre-commit-config.yaml 的 additional_dependencies、
脚本的 PEP 723 头、workflow 里每处调用都带 --with pyyaml==${PYYAML_VERSION}、无 pyyaml 时明确退出 2。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
CI = REPO / "scripts" / "ci"
YAML_SCRIPTS = ["secret_scan.py", "gitleaks_report.py", "check_fixtures.py", "check_gateway_limits.py"]
WORKFLOWS = [REPO / ".github/workflows/secret-scan.yml", REPO / ".github/workflows/ci.yml"]
PIN_RE = re.compile(r"pyyaml==([0-9][0-9A-Za-z.]*)")


def _workflow_pin(p: Path) -> str:
    return str(yaml.safe_load(p.read_text(encoding="utf-8"))["env"]["PYYAML_VERSION"])


def _pinned() -> str:
    return _workflow_pin(WORKFLOWS[0])


def test_workflows_agree():
    assert {_workflow_pin(p) for p in WORKFLOWS} == {_pinned()}
    assert re.fullmatch(r"\d+\.\d+\.\d+", _pinned()), "PYYAML_VERSION 必须是精确版本"


def test_pre_commit_pins_same_version():
    cfg = yaml.safe_load((REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [h for r in cfg["repos"] for h in r["hooks"] if "secret_scan.py" in str(h.get("entry", ""))]
    assert hooks, "pre-commit 里应有 secret_scan.py 钩子"
    for h in hooks:
        assert h["language"] == "python"
        assert h.get("additional_dependencies") == [f"pyyaml=={_pinned()}"]


def test_pep723_headers_pin_same_version():
    for name in YAML_SCRIPTS:
        text = (CI / name).read_text(encoding="utf-8")
        m = re.search(r"^# /// script\n(.*?)^# ///$", text, re.S | re.M)
        assert m, f"{name} 缺少 PEP 723 头"
        assert f'dependencies = ["pyyaml=={_pinned()}"]' in m.group(1), name
        # 正文里写死的版本号（错误提示、说明）也必须一致
        assert set(PIN_RE.findall(text)) == {_pinned()}, name


def test_every_workflow_invocation_installs_pyyaml():
    for wf in WORKFLOWS:
        for line in wf.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            for name in YAML_SCRIPTS:
                if f"scripts/ci/{name}" in line:
                    assert 'uv run --no-project' in line and '--with "pyyaml==${PYYAML_VERSION}"' in line, (
                        f"{wf.name}: {line.strip()}"
                    )


def test_missing_pyyaml_fails_fast_with_message():
    # -S：不加载 site-packages，模拟没有 pyyaml 的干净解释器
    r = subprocess.run(
        [sys.executable, "-S", str(CI / "secret_scan.py"), "files", str(CI / "secret_scan.py")],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 2
    assert f"pyyaml=={_pinned()}" in r.stderr
    assert "Traceback" not in r.stderr


def test_local_wrapper_uses_pep723():
    text = (CI / "secret_scan.sh").read_text(encoding="utf-8")
    assert "--script" in text and "secret_scan.py" in text
    assert (CI / "secret_scan.sh").stat().st_mode & 0o111
