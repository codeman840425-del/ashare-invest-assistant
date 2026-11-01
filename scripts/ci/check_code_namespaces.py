#!/usr/bin/env python3
"""三类码命名空间不重名（契约 v0.2 变更记录、§1 大小写规则、§9 命名空间要点；plan §8 第 2775 行附近）。

检查：
1. 错误码（§4）、原因码（§6.1）、导入提示码（§4.1 ``IMPORT_*``）三者两两不重名；
   门禁码 G1–G7 同属码类，也不得与三者重名。
2. 每一类内部不重复；码类取值全部匹配 ``^[A-Z][A-Z0-9_]*$``；导入提示码都以 ``IMPORT_`` 开头；
   原因码与门禁码不得使用 ``IMPORT_`` 前缀（§4 里 4 个批次级 HTTP 错误码 ``IMPORT_*`` 是错误码，按第 1 条查重）。
3. 给了 ``--meta-json``（后端 ``GET /api/v1/meta/enums`` 的响应）时，对后端下发的三类码做同样检查，
   并要求普通枚举取值匹配 ``^[a-z0-9][a-z0-9_]*$``。

用法：python3 scripts/ci/check_code_namespaces.py [--meta-json meta.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract_md as cm  # noqa: E402


def check(namespaces: dict[str, list[str]], label: str) -> list[str]:
    errors: list[str] = []
    for name, codes in namespaces.items():
        dup = [c for c, n in Counter(codes).items() if n > 1]
        if dup:
            errors.append(f"[{label}] {name} 内部重复：{sorted(dup)}")
        bad = [c for c in codes if not cm.CODE_RE.fullmatch(c)]
        if bad:
            errors.append(f"[{label}] {name} 取值不是大写码：{sorted(bad)}")
    for (a, ca), (b, cb) in combinations(namespaces.items(), 2):
        clash = sorted(set(ca) & set(cb))
        if clash:
            errors.append(f"[{label}] {a} 与 {b} 重名：{clash}")
    imp = namespaces.get("import_codes", [])
    bad_prefix = [c for c in imp if not c.startswith("IMPORT_")]
    if bad_prefix:
        errors.append(f"[{label}] 导入提示码必须以 IMPORT_ 开头：{bad_prefix}")
    for other in ("reason_codes", "gate_codes"):
        stray = [c for c in namespaces.get(other, []) if c.startswith("IMPORT_")]
        if stray:
            errors.append(f"[{label}] {other} 不得使用 IMPORT_ 前缀：{stray}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--meta-json", type=Path, help="后端 /meta/enums 响应 JSON")
    args = ap.parse_args()

    text = cm.contract_text()
    contract_ns = {
        "error_codes": list(cm.error_codes(text)),
        "reason_codes": cm.reason_codes(text),
        "import_codes": [r.code for r in cm.import_codes(text)],
        "gate_codes": cm.gate_codes(text),
    }
    errors = check(contract_ns, "契约")
    print(
        "契约码表：" + "，".join(f"{k}={len(v)}" for k, v in contract_ns.items()),
    )

    if args.meta_json:
        meta = json.loads(args.meta_json.read_text(encoding="utf-8"))
        backend_ns = {
            "error_codes": [e["code"] for e in meta.get("error_codes", [])],
            "reason_codes": [r["code"] for r in meta.get("reason_codes", [])],
            "import_codes": [i["code"] for i in meta.get("import_codes", [])],
        }
        gates = meta.get("enums", {}).get("gate")
        if gates is not None:
            backend_ns["gate_codes"] = list(gates)
        errors += check(backend_ns, "后端 /meta/enums")
        for name, values in meta.get("enums", {}).items():
            if name == "gate":
                continue
            bad = [v for v in values if not cm.ENUM_VALUE_RE.fullmatch(str(v))]
            if bad:
                errors.append(f"[后端 /meta/enums] 普通枚举 {name} 取值不是小写 snake_case：{bad}")
        print("后端码表：" + "，".join(f"{k}={len(v)}" for k, v in backend_ns.items()))

    for e in errors:
        print(f"::error title=code-namespace::{e}")
    if errors:
        print(f"三类码命名空间检查失败：{len(errors)} 项")
        return 1
    print("三类码命名空间检查通过：无重名、全部为大写码")
    return 0


if __name__ == "__main__":
    sys.exit(main())
