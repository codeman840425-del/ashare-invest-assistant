#!/usr/bin/env python3
"""源码不得被 .gitignore 误伤（T-O09a）。只用标准库和 git，不改任何文件。

背景：.gitignore 里的宽规则 licence.* 把 src/frontend/src/mocks/licence.ts 也忽略了。作者本地能跑，
提交里却缺这个文件，CI 才发现。本脚本在 CI 的干净检出上运行，以下任一项命中就退出 1：

1. tracked   已跟踪的 src/、tests/、scripts/ 源码（*.ts *.tsx *.py 等）被忽略规则命中
             （文件已提交时 git 不会报，但同目录同名新文件会被悄悄忽略）。
2. imports   已跟踪源码里的相对 import / require / vi.mock（TS/JS）和 import / from（Python，含相对导入），
             目标没有被跟踪，而且候选路径被忽略规则命中——也就是“引用了一个被 .gitignore 挡在提交外的文件”。
             目标不存在但没被忽略的不在这里报（tsc / mypy 会报）。
3. canary    在每个含已跟踪源码的目录里，用一组敏感词文件名（licence.ts、secrets.py、keys.ts……）
             做 git check-ignore --no-index，命中即说明有按“词”匹配的宽规则。
             目录级探针（<目录>/data/x.py 等）只告警，不失败。
4. --worktree（只在本机用，CI 不需要）：工作树里未跟踪、已被忽略的源码文件。只读，不删除任何文件。

用法：python3 scripts/ci/check_ignored_sources.py [--repo DIR] [--worktree]
"""
from __future__ import annotations

import argparse
import ast
import posixpath
import re
import subprocess
import sys
from pathlib import Path

SRC_ROOTS = ("src/", "tests/", "scripts/")
TS_EXT = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
PY_EXT = (".py",)
SOURCE_EXT = TS_EXT + PY_EXT
# 构建产物 / 依赖目录不算源码
SKIP_PARTS = {"node_modules", "dist", "build", "__pycache__", ".venv", "coverage"}

TS_RESOLVE_EXT = ("", ".ts", ".tsx", ".d.ts", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".json",
                  ".css", ".scss", ".less", ".svg", ".png")
TS_INDEX = ("index.ts", "index.tsx", "index.js", "index.jsx", "index.mts", "index.mjs")
_Q = r"""(['"])(\.{1,2}/[^'"\n]*)\1"""
TS_IMPORT_RES = [
    re.compile(r"\b(?:import|export)\b[^;'\"`]*?\bfrom\s*" + _Q),
    re.compile(r"\bimport\s*" + _Q),
    re.compile(r"\bimport\s*\(\s*" + _Q),
    re.compile(r"\brequire\s*\(\s*" + _Q),
    re.compile(r"\b(?:vi|jest)\.(?:mock|doMock|unmock|importActual|importMock|requireActual)\s*\(\s*" + _Q),
]
# Python 绝对导入在这些根下解析（只有首段在该根下有已跟踪文件时才算本仓库的模块，避免把 stdlib 的 secrets 等算进来）
PY_ROOTS = ("src/backend", "", "scripts/ci", "tests")

CANARY_WORDS = ("licence", "license", "licences", "mairui_licence", "secret", "secrets", "key", "keys",
                "private_keys", "public_keys", "cert", "certs", "credentials", "token", "env", "data",
                "statement", "statements", "import", "imports", "upload", "uploads", "samples", "backup")
CANARY_EXT = (".ts", ".tsx", ".py")
CANARY_DIRS = ("licence", "licences", "secrets", "keys", "data", "imports", "uploads", "statements", "samples")


def git(repo: Path, *args: str, stdin: str | None = None, ok: tuple[int, ...] = (0,)) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, text=True)
    if r.returncode not in ok:
        sys.stderr.write(r.stderr)
        raise SystemExit(f"git {' '.join(args[:2])} 失败（退出码 {r.returncode}）")
    return r.stdout


def ignored(repo: Path, paths: list[str]) -> dict[str, str]:
    """路径 -> 命中的规则（来源:行号:模式）。按规则判断，不看文件在不在、有没有被跟踪。"""
    if not paths:
        return {}
    out = git(repo, "check-ignore", "--no-index", "-v", "--stdin", stdin="\n".join(paths) + "\n", ok=(0, 1))
    res: dict[str, str] = {}
    for line in out.splitlines():
        src, _, path = line.partition("\t")
        if path:
            res[path] = src
    return res


def is_source(path: str) -> bool:
    if not path.startswith(SRC_ROOTS) or not path.endswith(SOURCE_EXT):
        return False
    return not (set(path.split("/")[:-1]) & SKIP_PARTS)


def ts_candidates(src: str, spec: str) -> list[str]:
    base = posixpath.normpath(posixpath.join(posixpath.dirname(src), spec.split("?")[0]))
    cands = [base + e for e in TS_RESOLVE_EXT] + [posixpath.join(base, i) for i in TS_INDEX]
    stem, ext = posixpath.splitext(base)
    if ext in (".js", ".jsx", ".mjs", ".cjs"):  # ESM 写法 './x.js' 实际指向 x.ts
        cands += [stem + e for e in (".ts", ".tsx", ".mts", ".cts")]
    return cands


def ts_specs(text: str) -> set[str]:
    specs: set[str] = set()
    for rx in TS_IMPORT_RES:
        specs.update(m.group(2) for m in rx.finditer(text))
    return specs


def py_module_candidates(base_dir: str, dotted: str) -> list[str]:
    parts = [p for p in dotted.split(".") if p]
    p = posixpath.join(base_dir, *parts) if base_dir else posixpath.join(*parts)
    return [p + ".py", posixpath.join(p, "__init__.py")]


def py_candidates(src: str, text: str, tracked_tops: dict[str, set[str]]) -> list[list[str]]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    groups: list[list[str]] = []
    pkg_dir = posixpath.dirname(src)
    for node in ast.walk(tree):
        # 每项：(level, 模块, 可选的子模块名)。from m import n：n 可能是子模块，也可能是 m 里的名字，
        # 所以 m 或 m.n 有一个被跟踪就算解析成功
        mods: list[tuple[int, str, str]] = []
        if isinstance(node, ast.Import):
            mods = [(0, a.name, "") for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [(node.level, node.module or "", a.name) for a in node.names if a.name != "*"] or \
                   [(node.level, node.module or "", "")]
        for level, mod, name in mods:
            dotted_full = ".".join(x for x in (mod, name) if x)
            if level:
                base = pkg_dir
                for _ in range(level - 1):
                    base = posixpath.dirname(base)
                bases = [base]
            else:
                top = dotted_full.split(".")[0]
                bases = [r for r in PY_ROOTS if top in tracked_tops.get(r, set())]
            for base in bases:
                cands = py_module_candidates(base, dotted_full) if dotted_full else []
                if mod and name:
                    cands += py_module_candidates(base, mod)
                elif not mod and level:  # from . import x 的“模块”是包本身
                    cands += [posixpath.join(base, "__init__.py")]
                groups.append(cands)
    return [g for g in groups if g]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="仓库根目录（默认当前目录）")
    ap.add_argument("--worktree", action="store_true", help="另查工作树里未跟踪且被忽略的源码（本机用）")
    a = ap.parse_args(argv)
    repo = Path(git(Path(a.repo), "rev-parse", "--show-toplevel").strip())

    tracked = git(repo, "ls-files", "-z").split("\0")
    tracked_set = set(filter(None, tracked))
    sources = sorted(p for p in tracked_set if is_source(p))
    errors: list[str] = []
    warnings: list[str] = []

    # 1. 已跟踪源码被规则命中
    for path, rule in sorted(ignored(repo, sources).items()):
        errors.append(f"tracked  {path}  被忽略规则命中（{rule}）")

    # 2. 引用指向被忽略的文件
    tracked_tops: dict[str, set[str]] = {}
    for root in PY_ROOTS:
        pre = root + "/" if root else ""
        tops: set[str] = set()
        for p in tracked_set:
            if p.startswith(pre) and p.endswith(".py"):
                tops.add(p[len(pre):].split("/")[0].removesuffix(".py"))
        tracked_tops[root] = tops
    refs: list[tuple[str, str, list[str]]] = []
    for src in sources:
        f = repo / src
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if src.endswith(TS_EXT):
            refs += [(src, spec, ts_candidates(src, spec)) for spec in sorted(ts_specs(text))]
        else:
            refs += [(src, "python import", c) for c in py_candidates(src, text, tracked_tops)]
    unresolved = [(s, spec, c) for s, spec, c in refs if not any(x in tracked_set for x in c)]
    hits = ignored(repo, sorted({x for _, _, c in unresolved for x in c}))
    seen: set[tuple[str, str]] = set()
    for src, spec, cands in unresolved:
        bad = [x for x in cands if x in hits]
        bad.sort(key=lambda x: "." not in posixpath.basename(x))  # 优先报带扩展名的候选（licence.ts 而不是 licence）
        if bad and (src, bad[0]) not in seen:
            seen.add((src, bad[0]))
            errors.append(f"imports  {src} 引用 {spec!r} -> {bad[0]} 没有被跟踪，且被忽略规则命中（{hits[bad[0]]}）")

    # 3. 敏感词文件名探针
    dirs = sorted({posixpath.dirname(p) for p in sources})
    probes = [posixpath.join(d, w + e) for d in dirs for w in CANARY_WORDS for e in CANARY_EXT]
    phit = ignored(repo, probes)
    for rule in sorted(set(phit.values())):
        sample = sorted(p for p, r in phit.items() if r == rule)
        errors.append(f"canary   规则 {rule} 会忽略源码文件名，例如新建 {sample[0]}（共 {len(sample)} 处）"
                      "——忽略规则太宽；改成按路径或扩展名精确匹配")
    dprobes = [posixpath.join(d, n, "index.ts") for d in dirs for n in CANARY_DIRS]
    dhit = ignored(repo, dprobes)
    for rule in sorted(set(dhit.values())):
        if "/" in rule.rsplit(":", 1)[-1].rstrip("/"):
            continue  # 写明路径的规则（如 src/backend/probes/samples/）是有意的
        sample = sorted(p for p, r in dhit.items() if r == rule)
        warnings.append(f"canary-dir 规则 {rule} 会忽略源码目录下的同名子目录，例如 {posixpath.dirname(sample[0])}/"
                        f"（共 {len(sample)} 处；只告警）")

    # 4. 工作树里未跟踪、已被忽略的源码（只读）
    if a.worktree:
        for p in git(repo, "ls-files", "-z", "-o", "-i", "--exclude-standard").split("\0"):
            if p and is_source(p):
                errors.append(f"worktree {p} 在工作树里存在但被忽略，不会进提交")

    for w in warnings:
        print(f"::warning title=ignored-sources::{w}")
    for e in errors:
        print(f"::error title=ignored-sources::{e}")
    n_ref = len(refs)
    print(f"ignored-sources：源码 {len(sources)} 个，引用 {n_ref} 处，探针 {len(probes)} 个；"
          f"错误 {len(errors)}，告警 {len(warnings)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
