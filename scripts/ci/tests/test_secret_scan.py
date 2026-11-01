"""secret_scan.py / .gitleaks.toml / .secretscan-allow.yaml / check_fixtures.py / check_licenses.py 正反例。"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

import secret_scan as ss
from cases import HOLDER, W, Case, cases, fake_token
from conftest import CI_DIR, REPO, commit_all, git, gitleaks_bin, write

ALLOW = ss.load_allow(REPO / ".secretscan-allow.yaml")
NO_SNAP = ss.Snapshot(lambda _p: None)


def py_scan(case: Case) -> tuple[set[str], set[str], list[ss.Finding]]:
    fs = ss.scan_blob(case.path, case.content.encode("utf-8"), NO_SNAP, ALLOW)
    return {f.rule for f in fs if f.level == ss.BLOCK}, {f.rule for f in fs if f.level == ss.WARN}, fs


@pytest.mark.parametrize("case", cases(), ids=lambda c: c.name)
def test_python_rules(case: Case) -> None:
    block, warn, fs = py_scan(case)
    assert block == case.py_block, [f.render() for f in fs]
    assert warn == case.py_warn, [f.render() for f in fs]


def test_every_rule_has_positive_and_negative() -> None:
    pos = set().union(*(c.py_block | c.py_warn for c in cases()))
    assert pos >= {f"S{i}" for i in range(1, 10)}
    negs = [c for c in cases() if not c.py_block and not c.py_warn]
    for i in range(1, 10):
        assert any(c.name.startswith(f"s{i}") for c in negs), f"S{i} 缺少不误报用例"


def test_output_is_masked(tmp_path: Path) -> None:
    secret = "s" + "k-" + fake_token(24)
    write(tmp_path, "a.py", f"k = '{secret}'\n")
    r = subprocess.run(
        [sys.executable, str(CI_DIR / "secret_scan.py"), "files", "a.py", "--repo", str(tmp_path),
         "--allow", str(REPO / ".secretscan-allow.yaml")],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert secret not in r.stdout + r.stderr
    assert "a.py:1:S2 sk*" in r.stdout


def test_gbk_text_is_s7() -> None:
    data = "\u4ea4\u5272\u5355\n".encode("gbk")  # 交割单
    fs = ss.scan_blob("data/x.txt", data, NO_SNAP, ALLOW)
    assert {f.rule for f in fs} == {"S7"}


def test_range_scan_catches_added_then_deleted(tmp_repo: Path) -> None:
    write(tmp_repo, "README", "x\n")
    base = commit_all(tmp_repo)
    write(tmp_repo, "src/leak.py", "k = '" + "s" + "k-" + fake_token(24) + "'\n")
    commit_all(tmp_repo)
    git(tmp_repo, "rm", "-q", "src/leak.py")
    head = commit_all(tmp_repo)
    r = subprocess.run([sys.executable, str(CI_DIR / "secret_scan.py"), "range", f"{base}..{head}", "--repo", str(tmp_repo)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "src/leak.py:1:S2" in r.stdout, r.stdout
    r = subprocess.run([sys.executable, str(CI_DIR / "secret_scan.py"), "commit", head, "--repo", str(tmp_repo)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


# ------------------------------------------------------------------ 夹具豁免
def _fixture(tmp_repo: Path, txt: str, *, fake: list[str] | None, origin: str = "generate.py",
             marker: str = "# SYNTHETIC", register: bool = True, sha_override: str | None = None) -> tuple[str, bytes]:
    d = "tests/fixtures/broker_statements/fmt_t"
    data = txt.encode("gbk")
    files = []
    if register:
        files.append({"file": "s.txt", "sha256": sha_override or hashlib.sha256(data).hexdigest(), "origin": origin})
    meta: dict = {"marker": marker, "synthetic": True, "files": files}
    if fake is not None:
        meta["fake_identifiers"] = fake
    write(tmp_repo, f"{d}/meta.json", json.dumps(meta))
    write(tmp_repo, f"{d}/s.txt", data)
    return f"{d}/s.txt", data


def _scan_fixture(tmp_repo: Path, path: str, data: bytes, allow: ss.AllowList = ALLOW) -> set[str]:
    snap = ss.Snapshot(lambda p: (tmp_repo / p).read_bytes() if (tmp_repo / p).is_file() else None)
    return {f.rule for f in ss.scan_blob(path, data, snap, allow)}


FIX_TXT = ",".join(W[:3]) + "\n" + HOLDER + " B" + "123456789 0" + "123456789\n"


def test_fixture_exempt_when_all_conditions_hold(tmp_repo: Path) -> None:
    path, data = _fixture(tmp_repo, FIX_TXT, fake=["B" + "123456789", "0" + "123456789"])
    assert _scan_fixture(tmp_repo, path, data) == set()


def test_fixture_value_outside_fake_identifiers_blocks(tmp_repo: Path) -> None:
    path, data = _fixture(tmp_repo, FIX_TXT, fake=["B" + "123456789"])
    assert _scan_fixture(tmp_repo, path, data) == {"S6"}


@pytest.mark.parametrize(
    "kw",
    [{"marker": "real"}, {"register": False}, {"sha_override": "0" * 64}, {"origin": "desensitized_main"}],
    ids=["no-marker", "unregistered", "sha-mismatch", "desensitized-unreviewed"],
)
def test_fixture_not_exempt(tmp_repo: Path, kw: dict) -> None:
    path, data = _fixture(tmp_repo, FIX_TXT, fake=["B" + "123456789", "0" + "123456789"], **kw)
    assert _scan_fixture(tmp_repo, path, data) == {"S5", "S6", "S7"}


def test_fixture_desensitized_registered(tmp_repo: Path) -> None:
    path, data = _fixture(tmp_repo, FIX_TXT, fake=["B" + "123456789", "0" + "123456789"], origin="desensitized_main")
    entry = {"rule": "*", "origin": "desensitized_main", "path": path, "sha256": hashlib.sha256(data).hexdigest(),
             "reviewer": "test-lead", "reason": "t", "added_by": "t", "added_at": "2026-11-01"}
    allow = ss.load_allow(None, yaml.safe_dump({"entries": [entry]}))
    assert not allow.errors
    assert _scan_fixture(tmp_repo, path, data, allow) == set()


def test_fixture_readme_never_exempt(tmp_repo: Path) -> None:
    _fixture(tmp_repo, FIX_TXT, fake=["B" + "123456789"])
    p = "tests/fixtures/broker_statements/fmt_t/README.md"
    assert _scan_fixture(tmp_repo, p, (",".join(W[:3]) + "\n").encode()) == {"S7"}


# ------------------------------------------------------------------ 允许清单
def test_allow_file_valid() -> None:
    assert ALLOW.errors == []


@pytest.mark.parametrize(
    "entry",
    [
        {"rule": "S5", "value_regex": "^A0+[0-9]$", "reason": "r", "added_by": "a", "added_at": "2026-11-01"},
        {"rule": "S5", "value_regex": ".*", "reason": "r", "added_by": "a", "added_at": "2026-11-01"},
        {"rule": "S5", "value_regex": "^A00000000" + "2$", "reason": "r", "added_by": "a"},
        {"rule": "S5", "reason": "r", "added_by": "a", "added_at": "2026-11-01"},
        {"rule": "*", "origin": "desensitized_main", "path": "x", "reason": "r", "added_by": "a", "added_at": "d"},
    ],
    ids=["wildcard", "dotstar", "missing-date", "missing-target", "desensitized-no-sha"],
)
def test_allow_file_rejects(entry: dict) -> None:
    assert ss.load_allow(None, yaml.safe_dump({"entries": [entry]})).errors


def test_allow_yaml_matches_gitleaks_toml() -> None:
    cfg = tomllib.loads((REPO / ".gitleaks.toml").read_text(encoding="utf-8"))
    toml_values = set()
    for a in cfg.get("allowlists", []):
        assert a.get("regexTarget") == "secret"
        assert not a.get("paths"), "全局允许清单不得按路径放行"
        toml_values |= set(a.get("regexes", []))
    data = yaml.safe_load((REPO / ".secretscan-allow.yaml").read_text(encoding="utf-8"))
    yaml_values = {e["value_regex"] for e in data["entries"] if e.get("value_regex")}
    assert toml_values == yaml_values
    for v in yaml_values:
        assert ss.LITERAL_REGEX.fullmatch(v), v


def test_gitleaks_config_has_s1_to_s9() -> None:
    cfg = tomllib.loads((REPO / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert cfg["extend"]["useDefault"] is True
    ids = {r["id"].split("-")[0] for r in cfg["rules"]}
    assert ids == {f"S{i}" for i in range(1, 10)}
    s7 = next(r for r in cfg["rules"] if r["id"].startswith("S7"))
    paths = [p for a in s7["allowlists"] for p in a.get("paths", [])]
    assert any(re.fullmatch(p, "docs/plan.md") for p in paths)
    assert not any(re.fullmatch(p, "docs/strategies/x.md") for p in paths)
    for r in cfg["rules"]:
        if not r["id"].startswith("S7"):
            for a in r.get("allowlists", []):
                assert not any(re.fullmatch(p, "docs/plan.md") for p in a.get("paths", [])), r["id"]


def test_config_files_do_not_trip_scanner() -> None:
    for rel in [".gitleaks.toml", ".secretscan-allow.yaml", "scripts/ci/secret_scan.py",
                "scripts/ci/tests/cases.py", "scripts/ci/tests/test_secret_scan.py", "scripts/ci/check_fixtures.py"]:
        fs = ss.scan_blob(rel, (REPO / rel).read_bytes(), NO_SNAP, ALLOW)
        assert [f.render() for f in fs] == [], rel


# ------------------------------------------------------------------ gitleaks 与同一批用例
@pytest.fixture(scope="module")
def gitleaks_results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[str]]:
    gl = gitleaks_bin()
    if gl is None:
        pytest.skip("未安装 gitleaks（CI 中由 GITLEAKS_BIN 提供）")
    repo = tmp_path_factory.mktemp("gl") / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    out: dict[str, str] = {}  # 每个用例单独一个提交：结果按 commit 归属到用例
    for c in cases():
        if c.gl_rules is None:
            continue
        write(repo, c.path, c.content)
        out[commit_all(repo, c.name)] = c.name
    report = repo.parent / "gl.json"
    subprocess.run([gl, "git", str(repo), "--no-banner", "-c", str(REPO / ".gitleaks.toml"), "--ignore-gitleaks-allow",
                    "-f", "json", "-r", str(report), "--exit-code", "0", "-l", "error"], check=True)
    findings = json.loads(report.read_text())
    by_case: dict[str, list[str]] = {c.name: [] for c in cases()}
    for f in findings:
        by_case[out[f["Commit"]]].append(f["RuleID"])
    return by_case


@pytest.mark.parametrize("case", [c for c in cases() if c.gl_rules is not None], ids=lambda c: c.name)
def test_gitleaks_rules(case: Case, gitleaks_results: dict[str, list[str]]) -> None:
    got = gitleaks_results[case.name]
    s_rules = {r.split("-")[0] for r in got if re.match(r"S\d-", r)}
    assert s_rules == case.gl_rules, got
    if not case.gl_rules and not case.py_block:
        assert got == [], got


# ------------------------------------------------------------------ 其他 CI 脚本
def test_check_licenses(tmp_repo: Path) -> None:
    write(tmp_repo, "web/package.json", json.dumps({"dependencies": {"ag-grid-community": "^34", "ag-grid-react": "^34"}}))
    commit_all(tmp_repo)
    cmd = [sys.executable, str(CI_DIR / "check_licenses.py"), "--repo", str(tmp_repo)]
    assert subprocess.run(cmd, capture_output=True).returncode == 0
    for dep in ("ag-grid-" + "enterprise", "@ag-grid-" + "enterprise/core"):
        write(tmp_repo, "web/package.json", json.dumps({"dependencies": {dep: "^34"}}))
        commit_all(tmp_repo)
        assert subprocess.run(cmd, capture_output=True).returncode == 1, dep



AGE = "ag-grid-" + "enterprise"


@pytest.mark.parametrize(
    ("rel", "body", "bad"),
    [
        ("web/package-lock.json", '{"packages": {"node_modules/' + AGE + '": {"version": "34.0.0"}}}', True),
        ("web/pnpm-lock.yaml", "packages:\n  " + AGE + "@34.0.0:\n    resolution: {}\n", True),
        ("web/pnpm-lock.yaml", "packages:\n  '@" + AGE + "/core@34.0.0':\n    resolution: {}\n", True),
        ("web/yarn.lock", AGE + '@^34:\n  version "34.0.0"\n', True),
        ("web/src/a.ts", "import { LicenseManager } from '" + AGE + "';\n", True),
        ("web/src/b.tsx", "import '@" + AGE + "/row-grouping';\n", True),
        ("web/src/c.js", "const x = require(\"" + AGE + "\");\n", True),
        ("web/src/d.ts", "const m = await import('" + AGE + "/dist');\n", True),
        ("web/package.json", '{"overrides": {"foo": {"' + AGE + '": "34"}}}', True),
        ("web/package.json", '{"dependencies": {"grid": "npm:' + AGE + '@34"}}', True),
        # 反例：防护代码本身（注释、eslint 规则、测试断言）中的包名不算依赖
        ("web/src/e.tsx", "// " + AGE + " is forbidden\nimport x from 'ag-grid-community';\n", False),
        ("web/eslint.config.js", "export default [{ rules: { 'no-restricted-imports': ['error', { patterns: [{ group: ['" + AGE + "'] }] }] } }];\n", False),
        ("web/src/f.test.ts", "expect(lock).not.toContain('" + AGE + "');\n", False),
        ("web/package.json", '{"description": "no ' + AGE + '", "dependencies": {"ag-grid-community": "34"}}', False),
    ],
)
def test_check_licenses_forms(tmp_repo: Path, rel: str, body: str, bad: bool) -> None:
    write(tmp_repo, rel, body)
    commit_all(tmp_repo)
    cmd = [sys.executable, str(CI_DIR / "check_licenses.py"), "--repo", str(tmp_repo)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == (1 if bad else 0), r.stdout

def test_check_coverage(tmp_path: Path) -> None:
    def cov(pkg_cov: int) -> Path:
        files = {
            "app/domain/a.py": {"summary": {"covered_lines": pkg_cov, "num_statements": 100}},
            "app/api/b.py": {"summary": {"covered_lines": 100, "num_statements": 100}},
        }
        p = tmp_path / f"c{pkg_cov}.json"
        p.write_text(json.dumps({"files": files}))
        return p

    run = lambda p: subprocess.run([sys.executable, str(CI_DIR / "check_coverage.py"), str(p)], capture_output=True)  # noqa: E731
    assert run(cov(95)).returncode == 0
    assert run(cov(85)).returncode == 1


# ------------------------------------------------------------------ 真实值精确比对 / gitleaks 报告掩码
def _real(repo: Path, mode: str, **env: str) -> subprocess.CompletedProcess[str]:
    import os

    e = {k: v for k, v in os.environ.items() if k not in ("MAIRUI_LICENCE", "DEEPSEEK_API_KEY")}
    e.update(env)
    return subprocess.run(["bash", str(CI_DIR / "check_real_secrets.sh"), mode], cwd=repo, env=e, capture_output=True, text=True)


def test_check_real_secrets(tmp_repo: Path) -> None:
    import secrets

    value = "fake" + secrets.token_hex(12)  # 每次运行随机生成，不是任何真实密钥
    other = "fake" + secrets.token_hex(12)
    write(tmp_repo, "a.txt", "nothing here\n")
    base = commit_all(tmp_repo)
    # 未配置：跳过并提示，退出 0
    r = _real(tmp_repo, "worktree")
    assert r.returncode == 0 and "跳过" in r.stdout
    # 不在仓库：not-found
    for mode in ("worktree", "cached", "history"):
        r = _real(tmp_repo, mode, MAIRUI_LICENCE=value, DEEPSEEK_API_KEY=other)
        assert r.returncode == 0, (mode, r.stdout)
    # 先加后删：工作区找不到，历史与区间能找到
    write(tmp_repo, "b.txt", f"k = {value}\n")
    commit_all(tmp_repo)
    write(tmp_repo, "b.txt", "removed\n")
    head = commit_all(tmp_repo)
    assert _real(tmp_repo, "worktree", MAIRUI_LICENCE=value).returncode == 0
    for mode in ("history", f"{base}..{head}"):
        r = _real(tmp_repo, mode, MAIRUI_LICENCE=value)
        assert r.returncode == 1 and "FOUND MAIRUI_LICENCE" in r.stdout, mode
        assert value not in r.stdout + r.stderr
    # 暂存区
    write(tmp_repo, "c.txt", f"x{other}x\n")
    git(tmp_repo, "add", "c.txt")
    r = _real(tmp_repo, "cached", DEEPSEEK_API_KEY=other)
    assert r.returncode == 1 and other not in r.stdout + r.stderr


def test_gitleaks_report_masks(tmp_path: Path) -> None:
    value = fake_token(30)
    rpt = tmp_path / "r.json"
    rpt.write_text(json.dumps([{"RuleID": "S1-mairui-licence-assign", "File": "a.py", "StartLine": 3, "Secret": value, "Match": "x=" + value}]))
    r = subprocess.run([sys.executable, str(CI_DIR / "gitleaks_report.py"), str(rpt)], capture_output=True, text=True)
    assert r.returncode == 1
    assert "a.py:3:S1-mairui-licence-assign " + value[:2] + "*" * 28 in r.stdout
    assert value not in r.stdout
    rpt.write_text("[]")
    assert subprocess.run([sys.executable, str(CI_DIR / "gitleaks_report.py"), str(rpt)], capture_output=True).returncode == 0
