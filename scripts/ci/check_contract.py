#!/usr/bin/env python3
"""契约文档对照脚本（plan §8 契约测试 = schemathesis + 本脚本；契约 §9 要点中可静态核对的部分）。

静态（只读 docs/）：
- §4.1 导入提示码共 46 个、21 个 error / 25 个 warning，且与 plan.md 3.5A-1 的表逐行一致；
- §4 错误码不重复；§6.1 原因码 22 个（v0.2.5 起；管理接口 /admin/* 不进公开 openapi.json，本脚本不读 openapi）。
对照后端（``--meta-json``，后端 ``GET /api/v1/meta/enums`` 的响应）：
- ``version`` 等于契约版本（契约变更记录最新一节）；
- ``enums`` 的键集合 == §3 表名（不含 ``reason_code``），每个取值逐项一致（含顺序）；
- ``error_codes`` 与 §4 的 code 集合与 HTTP 状态一致；``reason_codes`` 与 §6.1 一致；
  ``import_codes`` 与 §4.1 一致（severity、scope 逐项相同），且 ``IMPORT_*`` 提示码不出现在 ``error_codes``。

用法：python3 scripts/ci/check_contract.py [--meta-json meta.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract_md as cm  # noqa: E402

EXPECTED_IMPORT_TOTAL = 46
EXPECTED_IMPORT_SEVERITY = {"error": 21, "warning": 25}
EXPECTED_REASON_TOTAL = 22  # 契约 §3 第 325 行“22 个；v0.2.5 删 PROFILE_OR_CONSENT_MISSING”，架构师裁定（review-T-B03a-…-B45 §6(b)）


def static_checks(text: str) -> list[str]:
    errors: list[str] = []
    contract_rows = cm.import_codes(text)
    plan_rows = cm.import_codes(cm.PLAN.read_text(encoding="utf-8"), source="plan")
    if len(contract_rows) != EXPECTED_IMPORT_TOTAL:
        errors.append(f"§4.1 导入提示码应为 {EXPECTED_IMPORT_TOTAL} 个，实际 {len(contract_rows)}")
    sev = dict(Counter(r.severity for r in contract_rows))
    if sev != EXPECTED_IMPORT_SEVERITY:
        errors.append(f"§4.1 级别分布应为 {EXPECTED_IMPORT_SEVERITY}，实际 {sev}")
    dup = [c for c, n in Counter(r.code for r in contract_rows).items() if n > 1]
    if dup:
        errors.append(f"§4.1 重复的码：{dup}")
    if [r.no for r in contract_rows] != list(range(1, len(contract_rows) + 1)):
        errors.append("§4.1 序号不连续")
    if len(plan_rows) != len(contract_rows):
        errors.append(f"plan 3.5A-1 有 {len(plan_rows)} 行，契约 §4.1 有 {len(contract_rows)} 行")
    for a, b in zip(contract_rows, plan_rows, strict=False):
        if a.cells != b.cells:
            errors.append(f"§4.1 与 plan 3.5A-1 第 {a.no} 行不一致：{a.code} / {b.code}")
    reasons = cm.reason_codes(text)
    if len(reasons) != EXPECTED_REASON_TOTAL or len(set(reasons)) != len(reasons):
        errors.append(f"§6.1 原因码应为 {EXPECTED_REASON_TOTAL} 个且不重复，实际 {len(reasons)}")
    cm.error_codes(text)  # 重复时抛错
    return errors


def contract_version(text: str) -> str:
    m = re.search(r"^### (v\d+\.\d+(?:\.\d+)?)", text, re.M)
    if not m:
        raise SystemExit("契约变更记录中找不到版本号")
    return m.group(1)


def meta_checks(text: str, meta: dict) -> list[str]:
    errors: list[str] = []
    want_version = contract_version(text)
    if meta.get("version") != want_version:
        errors.append(f"/meta/enums version={meta.get('version')!r}，契约为 {want_version!r}")

    want_enums = {k: v for k, v in cm.enums(text).items() if k != "reason_code"}
    got_enums = meta.get("enums", {})
    missing = sorted(set(want_enums) - set(got_enums))
    extra = sorted(set(got_enums) - set(want_enums))
    if missing:
        errors.append(f"/meta/enums 缺少契约 §3 的枚举：{missing}")
    if extra:
        errors.append(f"/meta/enums 多出契约 §3 没有的枚举：{extra}")
    for name in sorted(set(want_enums) & set(got_enums)):
        if list(got_enums[name]) != want_enums[name]:
            errors.append(f"枚举 {name}：后端 {got_enums[name]} ≠ 契约 {want_enums[name]}")

    want_err = cm.error_codes(text)
    got_err = {e["code"]: e.get("http_status") for e in meta.get("error_codes", [])}
    for code in sorted(set(want_err) - set(got_err)):
        errors.append(f"error_codes 缺少 §4 的 {code}")
    for code in sorted(set(got_err) - set(want_err)):
        errors.append(f"error_codes 多出 §4 没有的 {code}")
    for code in sorted(set(want_err) & set(got_err)):
        if got_err[code] != want_err[code]:
            errors.append(f"{code} 的 HTTP 状态：后端 {got_err[code]} ≠ 契约 {want_err[code]}")

    want_reason = cm.reason_codes(text)
    got_reason = [r["code"] for r in meta.get("reason_codes", [])]
    if sorted(got_reason) != sorted(want_reason):
        errors.append(
            "reason_codes 与 §6.1 不一致："
            f"缺 {sorted(set(want_reason) - set(got_reason))}，多 {sorted(set(got_reason) - set(want_reason))}"
        )

    want_imp = {r.code: (r.severity, r.scope) for r in cm.import_codes(text)}
    got_imp = {i["code"]: (i.get("severity"), i.get("scope")) for i in meta.get("import_codes", [])}
    for code in sorted(set(want_imp) - set(got_imp)):
        errors.append(f"import_codes 缺少 §4.1 的 {code}")
    for code in sorted(set(got_imp) - set(want_imp)):
        errors.append(f"import_codes 多出 §4.1 没有的 {code}")
    for code in sorted(set(want_imp) & set(got_imp)):
        if got_imp[code] != want_imp[code]:
            errors.append(f"{code} 的 severity/scope：后端 {got_imp[code]} ≠ 契约 {want_imp[code]}")
    leaked = sorted(set(want_imp) & set(got_err))
    if leaked:
        errors.append(f"IMPORT_* 提示码不得出现在 error_codes：{leaked}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--meta-json", type=Path, help="后端 /meta/enums 响应 JSON")
    args = ap.parse_args()
    text = cm.contract_text()
    errors = static_checks(text)
    if args.meta_json:
        errors += meta_checks(text, json.loads(args.meta_json.read_text(encoding="utf-8")))
    for e in errors:
        print(f"::error title=contract-doc::{e}")
    if errors:
        print(f"契约文档对照失败：{len(errors)} 项")
        return 1
    print("契约文档对照通过" + ("（含后端 /meta/enums）" if args.meta_json else "（仅文档）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
