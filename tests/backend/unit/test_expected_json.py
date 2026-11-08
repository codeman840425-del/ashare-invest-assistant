"""T-T26 整合：保留已验收夹具/契约断言，并恢复 T-T01 原后端占位语义。"""
from __future__ import annotations

import json
import os
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TESTS_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = TESTS_DIR.parent
FMT_A = TESTS_DIR / "fixtures" / "broker_statements" / "fmt_a"
META = json.loads((FMT_A / "meta.json").read_text(encoding="utf-8"))
META_FILES = {e["file"]: e for e in META["files"]}
EXP = json.loads((FMT_A / "expected.json").read_text(encoding="utf-8"))
CODES_DOC = json.loads(Path(__file__).with_name("import_codes.json").read_text(encoding="utf-8"))
CODES = {c["code"]: c for c in CODES_DOC["codes"]}

# 契约 v0.2.2 §3（枚举）与 §4（导入相关 HTTP 码）
IMPORT_ROW_STATUS = {"ok", "warning", "error", "skipped"}
DEDUP_STATUS = {"new", "duplicate_in_db", "duplicate_in_file", "possible_duplicate_of_manual"}
IMPORT_STATUS = {"uploaded", "parsing", "previewed", "committed", "failed", "discarded", "reverted"}
RECON_KINDS = {"quantity_mismatch", "missing_in_broker", "missing_in_ours", "cost_differs", "cash_gap", "cash_chain_break"}
IMPORT_HTTP_CODES = {"IMPORT_FILE_ERRORS", "IMPORT_ROW_ERRORS", "IMPORT_WARNINGS_UNACKNOWLEDGED", "IMPORT_NOTHING_TO_COMMIT"}
PARSERS = {"trades": "tdx_trades_v1", "positions": "tdx_positions_v1"}
ROW_KINDS = {"trade", "event", "ignored", "snapshot_position"}


def _all_used_codes() -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}

    def add(code: str, where: str) -> None:
        used.setdefault(code, []).append(where)

    for name, f in EXP["files"].items():
        for c in f["file_findings"]:
            add(c, f"{name}:file")
        for r in f["rows"]:
            for c in r.get("codes", []):
                add(c, f"{name}:{r['row_no']}")
    for s in EXP["scenarios"]:
        add(s["code"], s["id"])
        for c in s["expect"].get("file_findings", []):
            add(c, s["id"])
        for r in s["expect"].get("rows", []) if isinstance(s["expect"].get("rows"), list) else []:
            for c in r.get("codes_include", []):
                add(c, s["id"])
    for gid, g in EXP["generated_cases"].items():
        add(g["code"], gid)
        for c in g["expect"].get("codes_include", []):
            add(c, gid)
    return used


# ---------------- 结构 ----------------
def test_header() -> None:
    assert EXP["marker"] == "# SYNTHETIC" and EXP["schema_version"] == 1
    assert EXP["contract"] == "api-contract v0.2.2"
    assert CODES_DOC["count"] == len(CODES) == 46
    assert sum(c["severity"] == "error" for c in CODES.values()) == 21


def test_one_to_one_with_meta() -> None:
    assert set(EXP["files"]) == set(META_FILES)


@pytest.mark.parametrize("name", sorted(META_FILES))
def test_file_entry_consistent_with_meta(name: str) -> None:
    f, m = EXP["files"][name], META_FILES[name]
    assert f["parser_id"] == PARSERS.get(m["kind"])
    assert f["parser_id"] == m["parser_hint"]
    if m["encoding"]:
        assert f["encoding"] in f["encoding_accept"]
    assert f["batch_status_after_preview"] in IMPORT_STATUS | {None}
    rows = {r["row_no"] for r in f["rows"]}
    assert len(rows) == len(f["rows"]), "row_no 重复"
    assert all(1 <= n <= m["physical_lines"] for n in rows), "row_no 超出物理行数"


@pytest.mark.parametrize("name", sorted(META_FILES))
def test_rows_status_and_codes(name: str) -> None:
    f = EXP["files"][name]
    for r in f["rows"]:
        assert r["status"] in IMPORT_ROW_STATUS
        assert r.get("dedup_status") in DEDUP_STATUS | {None}
        assert r.get("kind", "trade") in ROW_KINDS
        sev = {CODES[c]["severity"] for c in r["codes"]}
        assert all(CODES[c]["scope"] in {"row", "field"} for c in r["codes"]), (name, r["row_no"])
        if r["status"] == "error":
            assert "error" in sev, (name, r["row_no"])
            assert r.get("dedup_status") is None, "错误行不参与去重"
        elif r["status"] in {"warning", "skipped"}:
            assert r["codes"] and sev == {"warning"}, (name, r["row_no"])
        else:
            assert not r["codes"]
        if r.get("dedup_status") in {"duplicate_in_db", "duplicate_in_file"}:
            assert r["status"] == "skipped"
    for c in f["file_findings"]:
        assert CODES[c]["scope"] == "file", (name, c)


@pytest.mark.parametrize("name", sorted(n for n, f in EXP["files"].items() if f["rows_asserted"]))
def test_row_counts_cover_listed_rows(name: str) -> None:
    f = EXP["files"][name]
    counts = f["row_counts"]
    assert set(counts) == IMPORT_ROW_STATUS
    listed: dict[str, int] = {}
    for r in f["rows"]:
        listed[r["status"]] = listed.get(r["status"], 0) + 1
    for st, n in listed.items():
        assert n <= counts[st], (name, st)
    # 未列出的数据行按 defaults 计为 ok
    if META_FILES[name]["kind"] == "trades":
        assert sum(counts.values()) == META_FILES[name]["data_lines"], name


@pytest.mark.parametrize("name", sorted(META_FILES))
def test_confirm_and_upload_use_http_codes(name: str) -> None:
    """HTTP 错误码以去前缀形式（http_error）记录，完整码 = "IMPORT_" + 值；expected.json 中的 IMPORT_* 只能是 §4.1 码（CI ②）。"""
    f = EXP["files"][name]
    if f["confirm"]:
        res = f["confirm"]["result"]
        assert res in {"committed", "rejected"}, res
        if res == "committed":
            assert "http_error" not in f["confirm"]
            assert f["confirm"]["http_status"] == 200
        else:
            full = "IMPORT_" + f["confirm"]["http_error"]
            assert full in IMPORT_HTTP_CODES, full
            assert full not in CODES, "confirm 的 HTTP 错误码不得是 §4.1 提示码"
            assert f["confirm"]["http_status"] == 422
    if f.get("upload"):
        assert "IMPORT_" + f["upload"]["http_error"] in IMPORT_HTTP_CODES
        assert f["upload"]["http_status"] == 422


def test_expected_json_import_strings_are_section_4_1_codes() -> None:
    """plan 3.5A-2 ② / scripts/ci/check_fixtures.py：expected.json 中出现的每个 IMPORT_* 都在 §4.1 码表。"""
    found = set(re.findall(r"\bIMPORT_[A-Z0-9_]+\b", (FMT_A / "expected.json").read_text(encoding="utf-8")))
    assert found <= set(CODES), sorted(found - set(CODES))


@pytest.mark.parametrize("name", sorted(META_FILES))
def test_reconciliation_kinds_are_enum(name: str) -> None:
    kinds = EXP["files"][name]["reconciliation_kinds"]
    assert kinds is None or set(kinds) <= RECON_KINDS


@pytest.mark.parametrize("name", sorted(n for n, f in EXP["files"].items() if f.get("same_as")))
def test_same_as_references_exist(name: str) -> None:
    sa = EXP["files"][name]["same_as"]
    other = META_FILES[sa["file"]]
    assert all(1 <= int(k) <= META_FILES[name]["physical_lines"] for k in sa["row_map"])
    assert all(1 <= int(v) <= other["physical_lines"] for v in sa["row_map"].values())


def test_cr_fixture_expected_matches_lf() -> None:
    cr, lf = EXP["files"]["trades_cr.txt"], EXP["files"]["trades_lf.txt"]
    for k in ("parser_id", "row_counts", "rows", "normalized", "same_as", "confirm", "file_findings"):
        assert cr[k] == lf[k], k


# ---------------- 码表 ----------------
def test_all_used_codes_are_v0_2_import_codes() -> None:
    unknown = {c: w for c, w in _all_used_codes().items() if c not in CODES}
    assert not unknown, unknown


def test_every_import_code_is_covered() -> None:
    missing = sorted(set(CODES) - set(_all_used_codes()))
    assert not missing, f"以下 §4.1 提示码没有夹具/场景/generated_cases 覆盖：{missing}"


def test_generated_cases_match_code_table() -> None:
    for gid, g in EXP["generated_cases"].items():
        assert gid.startswith("GEN-")
        assert g["scope"] == CODES[g["code"]]["scope"], gid
        assert g["code"] in g["expect"]["codes_include"], gid


def test_removed_v0_1_codes_absent() -> None:
    text = (FMT_A / "expected.json").read_text(encoding="utf-8")
    for old in ("DATA_STALE", "preview_ready", "fmt_a_trades_v1\"", "\"confirmed\""):
        assert old not in text, old


def test_namespaces_disjoint_from_http_codes() -> None:
    assert not (set(CODES) & IMPORT_HTTP_CODES)


# ---------------- 对账：摊薄成本计入红利（契约 v0.2.2 /reconciliation，plan 3.5A、问题 19） ----------------
RECON_CASES = {c["id"]: c for c in EXP["reconciliation_cost_cases"]}
Q4 = Decimal("0.0001")


def _ledger(case: dict) -> list[dict]:
    led = case["ledger"]
    if isinstance(led, str):
        assert led.startswith("same_as:")
        return _ledger(RECON_CASES[led.split(":", 1)[1]])
    return led


def ref_diluted_cost(ledger: list[dict]) -> tuple[int, Decimal]:
    """参考实现：摊薄成本价 =（买入金额 + 费用 − 卖出回款 − 现金红利 + 股息红利税补缴 − Σother.net）÷ 持股数。"""
    qty, total = 0, Decimal(0)
    for e in ledger:
        t = e["type"]
        if t == "buy":
            qty += e["qty"]
            total += Decimal(e["amount"])
        elif t == "sell":
            qty -= e["qty"]
            total -= Decimal(e["amount"])
        elif t in {"fee", "dividend_tax"}:
            total += Decimal(e["amount"])
        elif t == "dividend":
            total -= Decimal(e["amount"])
        elif t == "other":  # 发生金额带符号：支出（负）计入成本
            total -= Decimal(e["net"])
        elif t == "bonus_shares":  # 送转股只加数量
            qty += e["qty"]
        else:
            raise AssertionError(f"未知流水类型 {t}")
    assert qty > 0
    return qty, (total / qty).quantize(Q4, rounding=ROUND_HALF_UP)


def ref_cost_items(ours: Decimal, broker: Decimal) -> list[dict]:
    diff = ours - broker
    tol = max(Decimal("0.01"), broker * Decimal("0.001"))
    if abs(diff) <= tol:
        return []
    return [{"kind": "cost_differs", "ours": str(ours), "broker": str(broker), "diff": str(diff)}]


def test_reconciliation_cases_present() -> None:
    assert len(RECON_CASES) == len(EXP["reconciliation_cost_cases"]) >= 5
    kinds = {e["type"] for c in RECON_CASES.values() for e in _ledger(c)}
    assert {"dividend", "dividend_tax", "other", "bonus_shares", "sell"} <= kinds


@pytest.mark.parametrize("cid", sorted(RECON_CASES))
def test_reconciliation_cost_case_oracle(cid: str) -> None:
    case = RECON_CASES[cid]
    qty, ours = ref_diluted_cost(_ledger(case))
    exp = case["expect"]
    assert (qty, str(ours)) == (exp["qty"], exp["ours_cost_price"])
    items = ref_cost_items(ours, Decimal(case["broker_cost_price"]))
    want = [{k: v for k, v in it.items() if k != "note_mentions"} for it in exp["items"]]
    assert items == want
    assert {it["kind"] for it in exp["items"]} <= RECON_KINDS
    for it in exp["items"]:
        assert it["note_mentions"], "cost_differs 须在 note 中提示可能原因"


def test_dividend_lowers_cost() -> None:
    """不计红利（v0.2.1 及以前的口径）会让 RC-COST-01 超容差——确认用例确实能区分两种口径。"""
    led = [e for e in _ledger(RECON_CASES["RC-COST-01"]) if e["type"] not in {"dividend", "dividend_tax"}]
    _, without = ref_diluted_cost(led)
    assert ref_cost_items(without, Decimal(RECON_CASES["RC-COST-01"]["broker_cost_price"]))


@pytest.mark.parametrize("cid", sorted(RECON_CASES))
def test_reconciliation_cost_case_backend(cid: str) -> None:
    pytest.skip("依赖后端 T-B19（对账引擎：摊薄成本重建计入 account_events 的红利与税费）及 T-B18 导入框架；接口就绪后按本用例的 ledger → /reconciliation 断言 items")


# ---------------- 与文档比对（需 v0.2.2 docs） ----------------
_VERSION_RE = re.compile(r"版本：\*\*v(\d+)\.(\d+)(?:\.(\d+))?\*\*")


def _docs_dir() -> Path:
    d = Path(os.environ.get("AIA_DOCS_DIR", REPO_ROOT / "docs"))
    c = d / "api-contract.md"
    m = _VERSION_RE.search(c.read_text(encoding="utf-8")) if c.is_file() else None
    ver = tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    if ver < (0, 2, 2):
        pytest.skip(f"{d} 不是 api-contract ≥ v0.2.2（依赖 T-A02 文档合入 main；可用 AIA_DOCS_DIR 指定）")
    return d


def test_contract_reconciliation_cost_includes_dividends() -> None:
    text = (_docs_dir() / "api-contract.md").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "`/reconciliation?account_id=`" in ln)
    assert "摊薄成本" in line and "现金红利冲减" in line and "max(0.01 元, 0.1%)" in line


ROW_RE = re.compile(r"^\| (\d+) \| `(IMPORT_[A-Z_]+)` \| (error|warning) \| (file|row|field) \|", re.M)


def _parse_code_table(text: str) -> list[dict]:
    return [{"no": int(n), "code": c, "severity": s, "scope": sc} for n, c, s, sc in ROW_RE.findall(text)]


#: 契约 v0.2.4 #11 在 §4.1 码表之后新增的“处理选项”表的起始标记
PROC_OPTIONS_MARK = "**处理选项"


def _section_4_1_code_table(text: str) -> str:
    """§4.1 中只含提示码表的那一段。

    跳过 v0.2.4 新增的“处理选项”表（``**处理选项（v0.2.4 #11，T-F02 D3）**`` 起到 ``## 5.``）：
    它不是提示码表，是 ``ImportFinding.resolution_choices`` 的生成规则，行格式与码表不同，
    且一行可合并多个提示码（如 26/27/28）；与 ``import_codes.json`` 比对时须排除，
    否则码表比对的语义会被新表干扰。该表单独由 ``test_contract_processing_options_*`` 对照
    ``resolution_choices.json`` 快照检查。
    """
    start, end = text.index("### 4.1"), text.index("## 5.")
    cut = text.find(PROC_OPTIONS_MARK, start, end)
    return text[start:cut if cut != -1 else end]


def test_snapshot_equals_contract_4_1() -> None:
    text = (_docs_dir() / "api-contract.md").read_text(encoding="utf-8")
    assert _parse_code_table(_section_4_1_code_table(text)) == CODES_DOC["codes"]


# ---------------- 契约 v0.2.4 §4.1 处理选项表（#11，T-F02 D3） ----------------
RESOLUTION = json.loads(Path(__file__).with_name("resolution_choices.json").read_text(encoding="utf-8"))
PROC_ROW_RE = re.compile(r"^\| ([\d/]+) (`IMPORT_[A-Z_]+`(?: / `IMPORT_[A-Z_]+`)*) \| `\[([a-z_, ]+)\]`[^|]* \| (.+?) \|$", re.M)
BACKEND_IMPORTS_PENDING = "导入/交易接口（/imports、/trades）后端未实现（T-B 导入任务）；契约 v0.2.4 §9 用例待接口落地后启用"


def _parse_processing_options(text: str) -> dict[str, dict]:
    start = text.index(PROC_OPTIONS_MARK)
    sec = text[start:text.index("## 5.", start)]
    out: dict[str, dict] = {}
    for nos, codes, choices, override in PROC_ROW_RE.findall(sec):
        names = re.findall(r"`(IMPORT_[A-Z_]+)`", codes)
        nums = [int(n) for n in nos.split("/")]
        assert len(nums) == len(names), nos
        for n, c in zip(nums, names):
            out[c] = {"no": n, "choices": [x.strip() for x in choices.split(",")],
                      "override": re.findall(r"`([a-z_]+)`", override)}
    return out


def _docs_v024() -> Path:
    d = _docs_dir()
    m = _VERSION_RE.search((d / "api-contract.md").read_text(encoding="utf-8"))
    if tuple(int(x or 0) for x in m.groups()) < (0, 2, 4):
        pytest.skip("docs 早于 v0.2.4：处理选项表来自契约 v0.2.4（T-A05 35f4880，未推到 origin）；可用 AIA_DOCS_DIR 指定")
    return d


def test_resolution_snapshot_codes_are_import_codes() -> None:
    for code, e in RESOLUTION["codes"].items():
        assert code in CODES and CODES[code]["no"] == e["no"], code
        assert e["choices"], code
        assert set(e["override"]) <= set(e["choices"]), code


def test_contract_processing_options_equal_snapshot() -> None:
    text = (_docs_v024() / "api-contract.md").read_text(encoding="utf-8")
    assert _parse_processing_options(text) == RESOLUTION["codes"]


@pytest.mark.skip(reason=BACKEND_IMPORTS_PENDING)
def test_backend_resolution_choices_match_contract_table() -> None:
    """§9 v0.2.4：预览响应中 ``ImportFinding.resolution_choices`` 与处理选项表一致，首项 = ``default_resolution``；表外提示码为 ``[]``/``null``。"""


@pytest.mark.skip(reason=BACKEND_IMPORTS_PENDING)
def test_backend_force_import_without_reason_is_400() -> None:
    """§9 v0.2.4：覆盖类选项（如 ``force_import``）提交时缺 ``reason`` → 400 VALIDATION_ERROR。"""


@pytest.mark.skip(reason=BACKEND_IMPORTS_PENDING)
def test_backend_void_trade_twice_is_409() -> None:
    """§9 v0.2.4：同一笔交易作废两次 → 409。"""


def test_snapshot_equals_plan_3_5a_1() -> None:
    plan = (_docs_dir() / "plan.md").read_text(encoding="utf-8")
    rows = _parse_code_table(plan)
    assert rows == CODES_DOC["codes"], "plan 3.5A-1 码表与契约 §4.1 快照不一致"


def test_contract_enums_match_constants() -> None:
    text = (_docs_dir() / "api-contract.md").read_text(encoding="utf-8")

    def enum(name: str) -> set[str]:
        m = re.search(rf"^\| `{name}` \| (.+?) \|$", text, re.M)
        assert m, name
        return set(re.findall(r"`([a-z_0-9]+)`", m.group(1).split("（")[0]))

    assert enum("import_row_status") == IMPORT_ROW_STATUS
    assert enum("dedup_status") == DEDUP_STATUS
    assert enum("import_status") == IMPORT_STATUS
    assert enum("reconciliation_item_kind") == RECON_KINDS


def test_contract_http_import_codes_are_422() -> None:
    text = (_docs_dir() / "api-contract.md").read_text(encoding="utf-8")
    sec = text[text.index("## 4. 错误码表"):text.index("### 4.1")]
    found = dict((c, int(s)) for s, c in re.findall(r"^\| (\d{3}) \| `(IMPORT_[A-Z_]+)` \|", sec, re.M))
    assert found == {c: 422 for c in IMPORT_HTTP_CODES}


_SUFFIXED = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")


def _market(code: str) -> str | None:
    """与后端 app.importing.preview.infer_market 同口径（920/4/8 → BJ；6/9/5、11 → SH；0/3/1/2 → SZ）。"""
    if code.startswith("920") or code[:1] in {"4", "8"}:
        return "BJ"
    if code[:1] in {"6", "9", "5"} or code.startswith("11"):
        return "SH"
    if code[:1] in {"0", "3", "1", "2"}:
        return "SZ"
    return None


def test_normalized_security_code_has_exchange_suffix() -> None:
    """规范化后的 security_code 按契约与栈的口径为“6 位代码 + .SH/.SZ/.BJ”（live 上传实测；600001.SH、
    301002.SZ、002001.SZ），后缀与代码前缀推断的交易所一致；不得是裸 6 位代码。"""
    seen = []
    for name, spec in EXP["files"].items():
        for n in spec.get("normalized") or []:
            if n.get("field") == "security_code":
                v = n["equals"]
                assert isinstance(v, str) and _SUFFIXED.match(v), (name, n["row_no"])
                assert v.split(".")[1] == _market(v[:6]), (name, n["row_no"])
                seen.append(v)
    assert {"600001.SH", "301002.SZ", "002001.SZ"} <= set(seen)


def test_quantity_match_keys_have_exchange_suffix() -> None:
    """scenario_with_trades.quantity_match 的键与 normalized security_code 同口径（6 位代码 + .SH/.SZ/.BJ，后缀与
    前缀推断一致），不得是裸 6 位代码。"""
    keys = []
    for name, spec in EXP["files"].items():
        for k in ((spec.get("scenario_with_trades") or {}).get("quantity_match") or {}):
            assert _SUFFIXED.match(k), (name, "quantity_match")
            assert k.split(".")[1] == _market(k[:6]), (name, "quantity_match")
            keys.append(k)
    assert keys, "expected.json 应至少有一处 quantity_match"
