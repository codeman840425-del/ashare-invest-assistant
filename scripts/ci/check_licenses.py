#!/usr/bin/env python3
"""依赖许可检查（plan.md §1048、§7.6、T-O02）。

1. 禁止 AG Grid Enterprise：扫描所有已跟踪的 package.json 依赖段、锁文件条目和前端源码 import/require，出现 `ag-grid-enterprise`
   或 `@ag-grid-enterprise/*` 即失败（注释、eslint 禁用规则、测试断言中的包名不算）；可传入 node_modules 目录检查已安装的传递依赖。
2. §7.6：Python 依赖许可证为 GPL、AGPL 或 NC（非商用）类即失败（LGPL 不在禁止之列）；
   用 --python 指向已安装依赖的解释器（如 src/backend/.venv/bin/python），读取包元数据
   （License-Expression、License、classifiers）。无法识别许可证的包只警告。
用法：check_licenses.py [--repo DIR] [--node-modules DIR ...] [--python PY ...]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN = re.compile(r"(?<![A-Za-z0-9_-])(?:@ag-grid-enterprise/[A-Za-z0-9._-]+|ag-grid-enterprise)(?![A-Za-z0-9_-])")
MANIFESTS = {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "npm-shrinkwrap.json", "bun.lock"}
SOURCE_SUFFIX = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".html"}
SELF = {"scripts/ci/check_licenses.py", "scripts/ci/tests/test_check_licenses.py"}


FORBIDDEN_LICENSE = re.compile(
    r"(?<![L\w])A?GPL|GNU (Affero )?General Public|Affero|\bNC\b|-NC-|Non-?Commercial", re.IGNORECASE
)
_DUMP = r"""
import json, importlib.metadata as md
out = []
for d in md.distributions():
    m = d.metadata
    parts = [m.get("License-Expression") or "", (m.get("License") or "").splitlines()[0] if m.get("License") else ""]
    parts += [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
    out.append({"name": m["Name"], "version": m["Version"], "licenses": [p for p in parts if p]})
print(json.dumps(out))
"""


def python_licenses(python: str) -> tuple[list[str], list[str]]:
    data = json.loads(subprocess.run([python, "-c", _DUMP], capture_output=True, check=True, text=True).stdout)
    bad, unknown = [], []
    for d in sorted(data, key=lambda x: x["name"].lower()):
        lic = "; ".join(d["licenses"])
        if not lic or lic.upper() == "UNKNOWN":
            unknown.append(f"{d['name']} {d['version']}")
        elif FORBIDDEN_LICENSE.search(lic):
            bad.append(f"{d['name']} {d['version']}: {lic}")
    return bad, unknown


def tracked(repo: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


DEP_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies",
                "bundleDependencies", "bundledDependencies", "overrides", "resolutions", "pnpm")
_NAME = r"(?:@ag-grid-enterprise/[A-Za-z0-9._-]+|ag-grid-enterprise)"
# 锁文件条目：package-lock 的 "node_modules/<名>" 与 "<名>": 键；pnpm-lock 的 <名>@版本 / '<名>@版本' / <名>: 键；yarn.lock 的 <名>@
LOCK_ENTRY = re.compile(r"(?:node_modules/|^\s*['\"]?|[\s/'\"])" + _NAME + r"(?:@|['\"]?\s*:)")
# 源码中的真实引用：import ... from '<名>'、import '<名>'、import('<名>')、require('<名>')、export ... from '<名>'
IMPORT_REF = re.compile(r"(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['\"`]" + _NAME + r"(?:/[^'\"`]*)?['\"`]")


def _walk_deps(obj: object, where: str) -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if FORBIDDEN.fullmatch(str(k)) or (isinstance(v, str) and FORBIDDEN.search(v.split(":", 1)[-1]) and v.startswith("npm:")):
                hits.append(f"{where}: {k}")
            hits += _walk_deps(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, str) and FORBIDDEN.fullmatch(v):
                hits.append(f"{where}: {v}")
    return hits


def scan_file(path: Path, rel: str) -> list[str]:
    """只认真实依赖：package.json 依赖段的键、锁文件条目、源码 import/require。

    注释、eslint 禁用规则、测试断言里出现包名不算（它们正是防护措施本身）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    if path.name == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return [f"{rel}: 无法解析 JSON"]
        if not isinstance(data, dict):
            return []
        return [f"{rel}: {h}" for sec in DEP_SECTIONS if sec in data for h in _walk_deps(data[sec], sec)]
    rx = LOCK_ENTRY if path.name in MANIFESTS else IMPORT_REF
    return [f"{rel}:{i}: {ln.strip()[:120]}" for i, ln in enumerate(text.splitlines(), 1) if rx.search(ln)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--node-modules", type=Path, action="append", default=[])
    ap.add_argument("--python", action="append", default=[])
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    hits: list[str] = []
    n = 0
    for rel in tracked(repo):
        p = repo / rel
        if rel in SELF or not p.is_file():
            continue
        if p.name in MANIFESTS or p.suffix in SOURCE_SUFFIX:
            n += 1
            hits += [f"禁止使用 AG Grid Enterprise（plan §7.6）：{h}" for h in scan_file(p, rel)]
    for nm in args.node_modules:
        for pkg in (nm / "ag-grid-enterprise", nm / "@ag-grid-enterprise", nm / ".pnpm"):
            if pkg.name == ".pnpm" and pkg.is_dir():
                hits += [f"禁止使用 AG Grid Enterprise：{d} 已安装" for d in pkg.iterdir() if FORBIDDEN.search(d.name.replace("+", "/"))]
            elif pkg.exists():
                hits.append(f"禁止使用 AG Grid Enterprise：{pkg} 已安装")
    for py in args.python:
        bad, unknown = python_licenses(py)
        for b in bad:
            hits.append(f"Python 依赖许可证为 GPL/AGPL/NC 类：{b}")
        for u in unknown:
            print(f"::warning title=license::无法识别许可证：{u}")
        print(f"Python 依赖（{py}）：禁止类 {len(bad)}，未识别 {len(unknown)}")
    for h in hits:
        print(f"::error title=license::{h}")
    print(f"check_licenses: 扫描 {n} 个清单/源码文件，命中 {len(hits)}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
