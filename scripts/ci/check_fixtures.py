#!/usr/bin/env python3
"""交割单夹具一致性检查（plan.md §7.4A 夹具豁免条件 1–5；§3.5A-2 CI 一致性检查 ①–③）。

对 tests/fixtures/broker_statements/ 下每个夹具目录：
  1. meta.json 存在，"marker" == "# SYNTHETIC" 且 "synthetic": true；
  2. 目录中每个 .txt 都在 meta.json.files[] 登记，登记的 sha256 与文件内容一致；登记了但不存在也算失败；
  3. origin=generate.py 的文件：在临时目录重新运行 generate.py --out，结果逐字节相同；
  4. origin=desensitized_main 的文件：.secretscan-allow.yaml 中有 path + sha256 + reviewer + added_at 条目；
  5. meta.json.fake_identifiers 存在，且 .txt 中所有 S5/S6 命中值都在其中；
  3.5A-2 ①：meta.json 的 .txt 集合与 expected.json.files 的键集合相等；
  3.5A-2 ②：expected.json 中出现的每个 IMPORT_* 码都在契约 §4.1；
  3.5A-2 ③：契约 §4.1 每个码至少被一个夹具 expected.json 覆盖；标“生成器”的码由 tests/ 下
            （夹具目录之外）的用例文件覆盖（以码字符串出现为准）。

任何失败退出码 1；输出不含夹具中的标识符原值（掩码）。
用法：check_fixtures.py [--repo DIR] [--root tests/fixtures/broker_statements] [--contract docs/api-contract.md]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract_md  # noqa: E402
import secret_scan as ss  # noqa: E402

FIXTURE_REL = "tests/fixtures/broker_statements"
IMPORT_CODE_RE = __import__("re").compile(r"\bIMPORT_[A-Z0-9_]+\b")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")
        print(f"::error title=check_fixtures::{where}: {msg}")

    def ok(self, where: str, msg: str) -> None:
        print(f"OK   {where}: {msg}")


def holder_code_values(text: str) -> set[str]:
    """按 S5/S6 规则（S6 含“股东”上下文）收集命中值。"""
    lines = text.splitlines()
    ctx = any(ss.HOLDER in ln for ln in lines[: ss.HEADER_CONTEXT_LINES])
    s5 = next(rx for rule, _lvl, rx in ss.LINE_RULES if rule == "S5")
    vals: set[str] = set()
    for ln in lines:
        vals.update(m.group(0) for m in s5.finditer(ln))
        if ctx or ss.HOLDER in ln:
            vals.update(m.group(0) for m in ss.S6_RE.finditer(ln))
    return vals


def regenerate(fdir: Path) -> Path | None:
    gen = fdir / "generate.py"
    if not gen.is_file():
        return None
    tmp = Path(tempfile.mkdtemp(prefix="fixture-regen-"))
    r = subprocess.run(
        [sys.executable, str(gen), "--out", str(tmp)],
        cwd=tmp,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
    )
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"generate.py 退出码 {r.returncode}: {r.stderr.strip()[-500:]}")
    return tmp


def check_dir(repo: Path, fdir: Path, allow: ss.AllowList, rep: Report) -> tuple[set[str], set[str]]:
    """返回 (expected.json 中出现的 IMPORT 码, 本目录 .txt 集合)。"""
    rel = fdir.relative_to(repo).as_posix()
    txts = {p.name for p in fdir.iterdir() if p.is_file() and p.suffix == ".txt"}
    meta_p = fdir / "meta.json"
    if not meta_p.is_file():
        rep.err(rel, "缺少 meta.json（条件 1）")
        return set(), txts
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        rep.err(rel, f"meta.json 无法解析：{e}")
        return set(), txts
    # 条件 1
    if meta.get("marker") != ss.FIXTURE_MARKER or meta.get("synthetic") is not True:
        rep.err(rel, 'meta.json 必须有 "marker": "# SYNTHETIC" 且 "synthetic": true（条件 1）')
    else:
        rep.ok(rel, "SYNTHETIC 标记")
    # 条件 2
    entries = {f.get("file"): f for f in meta.get("files", []) if isinstance(f, dict)}
    for name in sorted(txts - set(entries)):
        rep.err(f"{rel}/{name}", "未在 meta.json.files 登记（条件 2）")
    for name in sorted(set(entries) - {p.name for p in fdir.iterdir() if p.is_file()}):
        rep.err(f"{rel}/{name}", "meta.json 登记了但文件不存在（条件 2）")
    digests: dict[str, str] = {}
    for name in sorted(txts & set(entries)):
        digests[name] = hashlib.sha256((fdir / name).read_bytes()).hexdigest()
        if entries[name].get("sha256") != digests[name]:
            rep.err(f"{rel}/{name}", "sha256 与 meta.json 登记不一致（条件 2）")
    # 条件 3
    gen_names = sorted(n for n, e in entries.items() if e.get("origin") == "generate.py")
    if gen_names:
        try:
            tmp = regenerate(fdir)
        except RuntimeError as e:
            rep.err(rel, f"重新运行 generate.py 失败（条件 3）：{e}")
            tmp = None
        if tmp is None and (fdir / "generate.py").is_file() is False:
            rep.err(rel, "存在 origin=generate.py 的文件但目录中没有 generate.py（条件 3）")
        elif tmp is not None:
            try:
                bad = [n for n in gen_names if not (tmp / n).is_file() or (tmp / n).read_bytes() != (fdir / n).read_bytes()]
                for n in bad:
                    rep.err(f"{rel}/{n}", "generate.py 重新生成的结果与仓库文件不是逐字节相同（条件 3）")
                if not bad:
                    rep.ok(rel, f"generate.py 逐字节复现 {len(gen_names)} 个文件")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    # 条件 4
    for name, e in sorted(entries.items()):
        if e.get("origin") == "desensitized_main":
            path = f"{rel}/{name}"
            ent = allow.desensitized_entry(path, digests.get(name, ""))
            if ent is None or not ent.get("added_at"):
                rep.err(path, "脱敏主样本未在 .secretscan-allow.yaml 按 path+sha256+reviewer+日期 登记（条件 4）")
            else:
                rep.ok(path, f"脱敏主样本已登记（reviewer {ent['reviewer']}）")
        elif e.get("origin") != "generate.py":
            rep.err(f"{rel}/{name}", f"origin 只能是 generate.py 或 desensitized_main，实际 {e.get('origin')!r}")
    # 条件 5
    fake = meta.get("fake_identifiers")
    if not isinstance(fake, list) or not fake:
        rep.err(rel, "meta.json 缺少顶层 fake_identifiers（条件 5，T-T09）")
        fake = []
    fake_set = {str(x) for x in fake}
    for name in sorted(txts) if fake_set else []:
        text, _gbk = ss.decode((fdir / name).read_bytes())
        if text is None:
            continue
        extra = holder_code_values(text) - fake_set
        if extra:
            shown = ", ".join(sorted(ss.mask(v) for v in extra))
            rep.err(f"{rel}/{name}", f"S5/S6 命中值不在 fake_identifiers 中：{shown}（条件 5）")
    # 3.5A-2 ①②
    codes: set[str] = set()
    exp_p = fdir / "expected.json"
    if not exp_p.is_file():
        rep.err(rel, "缺少 expected.json（3.5A-2 ①）")
        return codes, txts
    try:
        exp = json.loads(exp_p.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        rep.err(rel, f"expected.json 无法解析：{e}")
        return codes, txts
    exp_files = set((exp.get("files") or {}).keys())
    meta_txts = {n for n in entries if n.endswith(".txt")}
    for n in sorted(meta_txts - exp_files):
        rep.err(f"{rel}/{n}", "在 meta.json 中但 expected.json.files 没有条目（3.5A-2 ①）")
    for n in sorted(exp_files - meta_txts):
        rep.err(f"{rel}/{n}", "在 expected.json.files 中但 meta.json 没有登记（3.5A-2 ①）")
    codes = set(IMPORT_CODE_RE.findall(exp_p.read_text(encoding="utf-8")))
    return codes, txts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=contract_md.REPO_ROOT)
    ap.add_argument("--root", default=FIXTURE_REL)
    ap.add_argument("--contract", type=Path)
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    root = repo / args.root
    rep = Report()
    allow = ss.load_allow(repo / ".secretscan-allow.yaml")
    for e in allow.errors:
        rep.err(".secretscan-allow.yaml", e)
    contract_text = (args.contract or repo / "docs" / "api-contract.md").read_text(encoding="utf-8")
    rows = contract_md.import_codes(contract_text)
    contract_codes = {r.code for r in rows}

    dirs = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if not dirs:
        rep.err(args.root, "没有夹具目录")
    covered: set[str] = set()
    for d in dirs:
        codes, _ = check_dir(repo, d, allow, rep)
        # 3.5A-2 ②
        for c in sorted(codes - contract_codes):
            rep.err(f"{d.relative_to(repo).as_posix()}/expected.json", f"{c} 不在契约 §4.1 表中（3.5A-2 ②）")
        covered |= codes & contract_codes

    # 3.5A-2 ③
    tests_dir = repo / "tests"
    gen_text = ""
    for p in tests_dir.rglob("*") if tests_dir.is_dir() else []:
        if p.is_file() and root not in p.parents and p.suffix in {".py", ".ts", ".json", ".yaml", ".yml"}:
            try:
                gen_text += p.read_text(encoding="utf-8") + "\n"
            except UnicodeDecodeError:
                pass
    gen_codes = set(IMPORT_CODE_RE.findall(gen_text))
    missing = []
    for r in rows:
        if r.code in covered:
            continue
        if r.generator_only and r.code in gen_codes:
            continue
        missing.append(f"{r.code}{'（生成器）' if r.generator_only else ''}")
    if missing:
        rep.err("3.5A-2 ③", f"{len(missing)} 个契约 §4.1 码没有被夹具或生成器用例覆盖：{', '.join(missing)}")
    else:
        rep.ok("3.5A-2 ③", f"契约 §4.1 的 {len(rows)} 个码全部覆盖")

    print(f"check_fixtures: {len(dirs)} 个夹具目录，{len(rep.errors)} 个失败")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
