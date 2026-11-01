"""check_contract.py 自测（T-O10）：原因码总数 = 22（契约第 325 行 + 架构师裁定），且脚本不在 openapi 里找 /admin/*。"""

from __future__ import annotations

import re
from pathlib import Path

import check_contract as cc
import contract_md as cm

SRC = Path(cc.__file__).read_text(encoding="utf-8")


def _meta_from_contract(text: str) -> dict:
    return {
        "version": cc.contract_version(text),
        "enums": {k: v for k, v in cm.enums(text).items() if k != "reason_code"},
        "error_codes": [{"code": c, "http_status": s} for c, s in cm.error_codes(text).items()],
        "reason_codes": [{"code": c} for c in cm.reason_codes(text)],
        "import_codes": [{"code": r.code, "severity": r.severity, "scope": r.scope} for r in cm.import_codes(text)],
    }


def test_expected_reason_total_is_22_and_matches_contract() -> None:
    text = cm.contract_text()
    assert cc.EXPECTED_REASON_TOTAL == 22
    assert len(cm.reason_codes(text)) == 22
    assert re.search(r"见 6\.1（22 个", text), "契约 §3 应写明 reason_code 22 个"
    assert cc.static_checks(text) == []


def test_static_check_rejects_wrong_reason_count() -> None:
    text = cm.contract_text()
    first = cm.reason_codes(text)[0]
    lines = text.splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.startswith("### 6.1 "))
    idx = next(i for i, ln in enumerate(lines) if i > start and ln.startswith("|") and f"`{first}`" in ln.split("|")[1])
    dropped = "".join(lines[:idx] + lines[idx + 1:])
    errs = cc.static_checks(dropped)
    assert any("§6.1 原因码应为 22 个" in e and "实际 21" in e for e in errs)
    duplicated = "".join(lines[: idx + 1] + [lines[idx]] + lines[idx + 1:])
    assert any("§6.1 原因码应为 22 个" in e for e in cc.static_checks(duplicated))


def test_meta_check_passes_without_any_admin_routes() -> None:
    """/admin/* 不进 openapi.json（架构师裁定 (a)）：后端数据里没有任何管理接口时对照必须通过。"""
    text = cm.contract_text()
    meta = _meta_from_contract(text)
    assert cc.meta_checks(text, meta) == []


def test_meta_check_flags_reason_code_drift() -> None:
    text = cm.contract_text()
    meta = _meta_from_contract(text)
    meta["reason_codes"] = meta["reason_codes"][1:]
    assert any(e.startswith("reason_codes 与 §6.1 不一致") for e in cc.meta_checks(text, meta))


def _looks_for_admin_in_openapi(src: str) -> bool:
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    return bool(re.search(r"openapi", code, re.I) and re.search(r"/admin", code))


def test_check_contract_does_not_look_for_admin_in_openapi() -> None:
    assert not _looks_for_admin_in_openapi(SRC)


def test_admin_openapi_guard_detects_offender() -> None:
    bad = 'paths = json.load(open("openapi.json"))["paths"]\nassert any(p.startswith("/admin") for p in paths)\n'
    assert _looks_for_admin_in_openapi(bad)
    assert not _looks_for_admin_in_openapi('"""openapi 与 /admin 只在文档字符串里提到"""\nx = 1\n')
