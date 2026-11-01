#!/usr/bin/env python3
"""密钥与敏感信息扫描 S1–S9（plan.md §7.4A；与 .gitleaks.toml 同一套规则，gitleaks 做不到的判定在这里做）。

gitleaks 负责正则类规则与其默认规则集；本脚本负责全部 S1–S9，额外覆盖：
  S4 文件存在性与 .env.example 取值、S6 “文件表头”上下文、S7 文件级判定（表头词 ≥3 或 GBK/GB18030 编码）、
  S8 身份证校验位、S9 Luhn、警告级别（手机号、银行卡）、夹具豁免条件、.secretscan-allow.yaml。

输出只有 ``path:line:rule 掩码值``（保留前 2 个字符，其余为 *），任何 block 级命中退出码 1。

用法：
  secret_scan.py tree                 # 当前检出的全部已跟踪文件（读磁盘）
  secret_scan.py commit REV           # 某个提交的完整文件树（读 git 对象，不受工作区改动影响）
  secret_scan.py staged               # 暂存区中新增/修改的文件（pre-commit）
  secret_scan.py range A..B           # 区间内每个提交新增/修改的每个文件版本（PR 全提交扫描、push 扫描）
  secret_scan.py history              # 全部历史（每日全量扫描）
  secret_scan.py files P [P ...]      # 指定的磁盘文件（自测用）
  --repo DIR                          # 仓库目录（默认当前目录）
  --allow FILE                        # 允许清单（默认 <repo>/.secretscan-allow.yaml）
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import posixpath
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

BLOCK, WARN = "block", "warn"

# 中文关键字一律用 \u 转义书写，避免本脚本自己命中 S6/S7。
HEADER_WORDS = (  # 交割单表头词，顺序同 plan §7.4A S7 规则表
    "\u6210\u4ea4\u65e5\u671f",
    "\u8bc1\u5238\u4ee3\u7801",
    "\u80a1\u4e1c\u4ee3\u7801",
    "\u6210\u4ea4\u7f16\u53f7",
    "\u59d4\u6258\u7f16\u53f7",
    "\u53d1\u751f\u91d1\u989d",
    "\u5269\u4f59\u91d1\u989d",
)
HOLDER = "\u80a1\u4e1c"  # 股东
ACCOUNT_RE = re.compile(
    "(?:\u8d44\u91d1\u8d26\u53f7|\u8d44\u91d1\u5e10\u53f7|\u5ba2\u6237\u53f7)\\s*[:\uff1a]?\\s*\\d{6,}"
)
HEADER_CONTEXT_LINES = 20  # S6：文件前 20 行视为“文件表头”

FIXTURE_ROOT = "tests/fixtures/broker_statements/"
FIXTURE_RULES = {"S5", "S6"}  # 夹具条件豁免（值须在 meta.json.fake_identifiers 中）
# S7 按路径豁免：docs/ 顶层 *.md（子目录不豁免）+ tests/fixtures/broker_statements/ 整个目录（T-O02 补充要求）
S7_EXEMPT_PATH = re.compile(r"^(?:docs/[^/]+\.md|tests/fixtures/broker_statements/.+)$")
FIXTURE_MARKER = "# SYNTHETIC"

A = re.ASCII  # \b 只按 ASCII 判定（与 gitleaks/RE2 一致：中文字符视为非单词字符）
LINE_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    ("S1", BLOCK, re.compile(r"(?i)mairuiapi\.com/\S+/[A-Za-z0-9-]{16,}", A)),
    ("S1", BLOCK, re.compile(r"""(?i)(mairui[_-]?)?licen[cs]e\s*[:=]\s*["']?[A-Za-z0-9-]{16,}""", A)),
    ("S2", BLOCK, re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b", A)),  # 启发式；真实值精确比对在本机 check_real_secrets.sh（CI 不做）
    (
        "S2",
        BLOCK,
        re.compile(
            r"""(?i)\b(api[_-]?key|secret|token|passwd|password)\b\s*[:=]\s*["'][^"'\s]{12,}["']""", A
        ),
    ),
    ("S3", BLOCK, re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", A)),
    ("S5", BLOCK, re.compile(r"\b[A-Z]\d{9}\b", A)),
    ("S9", BLOCK, ACCOUNT_RE),
]
S6_RE = re.compile(r"\b0\d{9}\b", A)
S8_ID_RE = re.compile(r"\b\d{17}[\dXx]\b", A)
S8_PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b", A)
S9_CARD_RE = re.compile(r"\b\d{16,19}\b", A)

ENV_FILE_RE = re.compile(r"(^|/)\.env[^/]*$")
ENV_EXAMPLE = ".env.example"
ENV_SENSITIVE_KEY = re.compile(r"^(APP_MASTER_KEY|MAIRUI_LICENCE|DATABASE_URL|[A-Z0-9_]*_PASSWORD|[A-Z0-9_]*_API_KEY)$")
ENV_PLACEHOLDER = re.compile(r"^(|changeme[A-Za-z0-9_.-]*|example[A-Za-z0-9_.-]*|<[^<>]+>)$")

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK = "10X98765432"


def id_checksum_ok(s: str) -> bool:
    total = sum(int(c) * w for c, w in zip(s[:17], _ID_WEIGHTS, strict=True))
    return _ID_CHECK[total % 11] == s[17].upper()


def luhn_ok(s: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def mask(value: str) -> str:
    return value[:2] + "*" * max(len(value) - 2, 0)


# --------------------------------------------------------------------------- 允许清单
@dataclass
class AllowList:
    value_entries: list[tuple[str, re.Pattern[str]]] = field(default_factory=list)  # (rule, regex)
    path_entries: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def value_allowed(self, rule: str, value: str) -> bool:
        return any(r in (rule, "*") and rx.fullmatch(value) for r, rx in self.value_entries)

    def path_allowed(self, rule: str, path: str, sha256: str) -> bool:
        for e in self.path_entries:
            if e["rule"] not in (rule, "*") or not fnmatch.fnmatchcase(path, e["path"]):
                continue
            if e.get("sha256") and e["sha256"] != sha256:
                continue
            return True
        return False

    def desensitized_entry(self, path: str, sha256: str) -> dict | None:
        for e in self.path_entries:
            if e["path"] == path and e.get("sha256") == sha256 and e.get("reviewer"):
                return e
        return None


REQUIRED_KEYS = ("rule", "reason", "added_by", "added_at")
# value_regex 只能是锚定的字面量（^...$，不含通配），保证允许的只是逐个列出的虚构值。
LITERAL_REGEX = re.compile(r"^\^(?:[A-Za-z0-9_\-]|\\\.)+\$$")


def load_allow(path: Path | None, text: str | None = None) -> AllowList:
    al = AllowList()
    if text is None:
        if path is None or not path.exists():
            al.errors.append(f"允许清单不存在：{path}")
            return al
        text = path.read_text(encoding="utf-8")
    import yaml  # 只在这里需要第三方库

    data = yaml.safe_load(text) or {}
    for i, e in enumerate(data.get("entries") or []):
        where = f"允许清单第 {i + 1} 项"
        missing = [k for k in REQUIRED_KEYS if not e.get(k)]
        if not (e.get("path") or e.get("value_regex")):
            missing.append("path|value_regex")
        if missing:
            al.errors.append(f"{where} 缺少字段：{missing}")
            continue
        e["added_at"] = str(e["added_at"])
        if e.get("value_regex"):
            vr = str(e["value_regex"])
            if not LITERAL_REGEX.fullmatch(vr):
                al.errors.append(f"{where} value_regex 必须是 ^字面量$ 形式的单个虚构值：{vr}")
                continue
            al.value_entries.append((str(e["rule"]), re.compile(vr)))
        if e.get("path"):
            if e.get("origin") == "desensitized_main" and not (e.get("sha256") and e.get("reviewer")):
                al.errors.append(f"{where} 脱敏主样本必须带 sha256 与 reviewer")
                continue
            al.path_entries.append(e)
    return al


# --------------------------------------------------------------------------- 快照读取
class Snapshot:
    """在同一时间点读取其他文件（夹具 meta.json）。"""

    def __init__(self, reader: Callable[[str], bytes | None]) -> None:
        self._reader = reader
        self._cache: dict[str, bytes | None] = {}

    def read(self, path: str) -> bytes | None:
        if path not in self._cache:
            self._cache[path] = self._reader(path)
        return self._cache[path]


def git(repo: Path, *args: str, input_: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], input=input_, capture_output=True, check=True
    ).stdout


def git_maybe(repo: Path, *args: str) -> bytes | None:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    return r.stdout if r.returncode == 0 else None


# --------------------------------------------------------------------------- 夹具豁免
@dataclass
class FixtureVerdict:
    exempt: bool
    fake_ids: set[str]
    why: str


FIXTURE_NOT_EXEMPT = {"README.md", "expected.json"}  # plan §7.4A：这两类文件不享受豁免


def fixture_verdict(path: str, data: bytes, snap: Snapshot, allow: AllowList) -> FixtureVerdict | None:
    """tests/fixtures/broker_statements/** 下文件的 S5/S6 豁免判定（None = 不在夹具目录；S7 整个目录按路径豁免）。

    .txt：meta.json 带 SYNTHETIC 标记、本文件登记在 files[] 且 sha256 一致、脱敏主样本已在允许清单登记；
    其他文件（generate.py、meta.json 等）：所在目录 meta.json 带 SYNTHETIC 标记；
    README.md、expected.json 一律不豁免。S5/S6 命中值还必须在 meta.json.fake_identifiers 中（见 scan_blob）。
    目录完整性（每个 .txt 都登记）与 generate.py 可复现由 check_fixtures.py 检查。
    """
    if not path.startswith(FIXTURE_ROOT):
        return None
    name = posixpath.basename(path)
    if name in FIXTURE_NOT_EXEMPT:
        return FixtureVerdict(False, set(), f"{name} 不享受夹具豁免")
    meta_raw = snap.read(posixpath.join(posixpath.dirname(path), "meta.json"))
    if meta_raw is None:
        return FixtureVerdict(False, set(), "缺少 meta.json")
    try:
        meta = json.loads(meta_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return FixtureVerdict(False, set(), "meta.json 无法解析")
    if meta.get("marker") != FIXTURE_MARKER or meta.get("synthetic") is not True:
        return FixtureVerdict(False, set(), "meta.json 缺少 SYNTHETIC 标记")
    fake_ids = {str(x) for x in meta.get("fake_identifiers", [])}
    if not name.endswith(".txt"):
        return FixtureVerdict(True, fake_ids, "ok")
    entry = next((f for f in meta.get("files", []) if f.get("file") == name), None)
    digest = hashlib.sha256(data).hexdigest()
    if entry is None:
        return FixtureVerdict(False, set(), "未登记在 meta.json.files")
    if entry.get("sha256") != digest:
        return FixtureVerdict(False, set(), "sha256 与 meta.json 不符")
    if entry.get("origin") == "desensitized_main" and allow.desensitized_entry(path, digest) is None:
        return FixtureVerdict(False, set(), "脱敏主样本未在允许清单登记（path+sha256+reviewer）")
    if entry.get("origin") not in ("generate.py", "desensitized_main"):
        return FixtureVerdict(False, set(), f"未知 origin {entry.get('origin')!r}")
    return FixtureVerdict(True, fake_ids, "ok")


# --------------------------------------------------------------------------- 单个文件
@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    level: str
    value: str
    where: str = ""

    def render(self) -> str:
        prefix = f"{self.where}:" if self.where else ""
        return f"{prefix}{self.path}:{self.line}:{self.rule} {mask(self.value)}"


def decode(data: bytes) -> tuple[str | None, bool]:
    """返回 (文本, 是否 GBK/GB18030)。二进制返回 (None, False)。"""
    if b"\x00" in data[:8192]:
        return None, False
    try:
        return data.decode("utf-8-sig"), False
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("gb18030"), True
    except UnicodeDecodeError:
        return data.decode("latin-1"), False


def scan_blob(path: str, data: bytes, snap: Snapshot, allow: AllowList, where: str = "") -> list[Finding]:
    out: list[Finding] = []
    digest = hashlib.sha256(data).hexdigest()
    base = posixpath.basename(path)

    def add(line: int, rule: str, level: str, value: str) -> None:
        if allow.value_allowed(rule, value) or allow.path_allowed(rule, path, digest):
            return
        if rule in FIXTURE_RULES and fx is not None and fx.exempt and value in fx.fake_ids:
            return
        out.append(Finding(path, line, rule, level, value, where))

    fx = fixture_verdict(path, data, snap, allow)

    # S4：.env* 文件（.env.example 除外）
    if ENV_FILE_RE.search(path) and base != ENV_EXAMPLE:
        add(0, "S4", BLOCK, base)

    text, is_gbk = decode(data)
    if text is None:
        return out
    lines = text.splitlines()

    if base == ENV_EXAMPLE:
        for no, line in enumerate(lines, 1):
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if not m or not ENV_SENSITIVE_KEY.match(m.group(1)):
                continue
            val = m.group(2).split(" #", 1)[0].strip().strip("'\"")
            if not ENV_PLACEHOLDER.fullmatch(val):
                add(no, "S4", BLOCK, f"{m.group(1)}={val}")

    header_has_holder = any(HOLDER in ln for ln in lines[:HEADER_CONTEXT_LINES])
    for no, line in enumerate(lines, 1):
        for rule, level, rx in LINE_RULES:
            for m in rx.finditer(line):
                add(no, rule, level, m.group(0))
        if header_has_holder or HOLDER in line:
            for m in S6_RE.finditer(line):
                add(no, "S6", BLOCK, m.group(0))
        for m in S8_ID_RE.finditer(line):
            if id_checksum_ok(m.group(0)):
                add(no, "S8", BLOCK, m.group(0))
        for m in S8_PHONE_RE.finditer(line):
            add(no, "S8", WARN, m.group(0))
        for m in S9_CARD_RE.finditer(line):
            if luhn_ok(m.group(0)):
                add(no, "S9", WARN, m.group(0))

    # S7：文件级
    if not S7_EXEMPT_PATH.match(path):
        hits = [w for w in HEADER_WORDS if w in text]
        if len(hits) >= 3:
            first = next(i for i, ln in enumerate(lines, 1) if any(w in ln for w in hits))
            add(first, "S7", BLOCK, "".join(hits))
        elif is_gbk:
            add(0, "S7", BLOCK, "GB18030")
    return out


# --------------------------------------------------------------------------- 扫描目标
def iter_tree(repo: Path) -> Iterator[tuple[str, bytes, Snapshot, str]]:
    snap = Snapshot(lambda p: (repo / p).read_bytes() if (repo / p).is_file() else None)
    for p in git(repo, "ls-files", "-z").decode().split("\0"):
        if p and (repo / p).is_file() and not (repo / p).is_symlink():
            yield p, (repo / p).read_bytes(), snap, ""


def iter_staged(repo: Path) -> Iterator[tuple[str, bytes, Snapshot, str]]:
    snap = Snapshot(lambda p: git_maybe(repo, "show", f":{p}"))
    names = git(repo, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT").decode().split("\0")
    for p in names:
        if p:
            data = snap.read(p)
            if data is not None:
                yield p, data, snap, "staged"


def iter_rev_tree(repo: Path, rev: str) -> Iterator[tuple[str, bytes, Snapshot, str]]:
    snap = Snapshot(lambda p: git_maybe(repo, "show", f"{rev}:{p}"))
    for rec in git(repo, "ls-tree", "-r", "-z", rev).decode("utf-8", "surrogateescape").split("\0"):
        if not rec:
            continue
        info, path = rec.split("\t", 1)
        mode, kind, sha = info.split()
        if kind == "blob" and mode != "120000":
            yield path, git(repo, "cat-file", "blob", sha), snap, rev[:10]


def iter_commits(repo: Path, revs: list[str]) -> Iterator[tuple[str, bytes, Snapshot, str]]:
    seen: set[tuple[str, str]] = set()
    commits = git(repo, "rev-list", "--reverse", *revs).decode().split()
    for c in commits:
        snap = Snapshot(lambda p, c=c: git_maybe(repo, "show", f"{c}:{p}"))
        raw = git(repo, "diff-tree", "-r", "-m", "--root", "--no-commit-id", "-z", "--diff-filter=ACMRT", c)
        parts = raw.decode("utf-8", "surrogateescape").split("\0")
        i = 0
        while i < len(parts) - 1:
            meta, path = parts[i], parts[i + 1]
            i += 2
            if not meta.startswith(":"):
                continue
            fields = meta[1:].split()
            new_mode, new_sha, status = fields[1], fields[3], fields[4]
            if status[0] in "RC":  # rename/copy：后面还有新路径
                path = parts[i]
                i += 1
            if new_mode in ("160000", "120000") or (path, new_sha) in seen:
                continue
            seen.add((path, new_sha))
            yield path, git(repo, "cat-file", "blob", new_sha), snap, c[:10]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="S1–S9 密钥与敏感信息扫描（plan §7.4A）")
    ap.add_argument("mode", choices=["tree", "commit", "staged", "range", "history", "files"])
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--allow", type=Path)
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    allow = load_allow(args.allow or repo / ".secretscan-allow.yaml")
    for e in allow.errors:
        print(f"::error title=secretscan-allow::{e}")

    it: Iterable[tuple[str, bytes, Snapshot, str]]
    if args.mode == "tree":
        it = iter_tree(repo)
    elif args.mode == "commit":
        if len(args.targets) != 1:
            ap.error("commit 需要一个提交参数")
        it = iter_rev_tree(repo, args.targets[0])
    elif args.mode == "staged":
        it = iter_staged(repo)
    elif args.mode == "range":
        if len(args.targets) != 1:
            ap.error("range 需要一个 A..B 参数")
        it = iter_commits(repo, [args.targets[0]])
    elif args.mode == "history":
        it = iter_commits(repo, ["--all"])
    else:
        snap = Snapshot(lambda p: (repo / p).read_bytes() if (repo / p).is_file() else None)
        it = ((p, (repo / p).read_bytes(), snap, "") for p in args.targets)

    blocks = warns = scanned = 0
    for path, data, snap, where in it:
        scanned += 1
        for f in scan_blob(path, data, snap, allow, where):
            if f.level == BLOCK:
                blocks += 1
                print(f.render())
                print(f"::error file={f.path},line={max(f.line, 1)},title={f.rule}::{f.rule} {mask(f.value)}")
            else:
                warns += 1
                print(f"WARN {f.render()}")
                print(f"::warning file={f.path},line={max(f.line, 1)},title={f.rule}::{f.rule} {mask(f.value)}")
    print(f"secret_scan {args.mode}: 扫描 {scanned} 个文件版本，阻断 {blocks}，警告 {warns}")
    return 1 if blocks or allow.errors else 0


if __name__ == "__main__":
    sys.exit(main())
