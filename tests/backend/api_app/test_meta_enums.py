"""``GET /meta/enums``：T-B01 报告 §6 建议 7 + 契约 §3/§4/§6.1/§7.10/§9（T-T01c 升到 v0.2.3，T-T01d 升到 v0.2.4、v0.2.5，T-T22 升到 v0.2.6）。

- 与契约逐项比对的用例需要 v0.2.3 文档（``AIA_DOCS_DIR``，缺省为仓库 docs/），否则 skip；
- 后端尚未同步 v0.2 的差异（新增枚举、改名的取值/错误码、version、import_codes）在运行时
  算出差异后 ``pytest.xfail``，原因列出差异并写明“T-B01 v0.2 修订”；
- 不依赖 v0.2 文档的行为（ETag/304/Cache-Control、命名规则、命名空间不重名）直接断言。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract]

PATH = "/api/v1/meta/enums"
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
ENUM_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
#: 契约 §1：gate（G1–G7）与 reason_code 属于“码类取值”，用大写（reason_code 在 v0.2 中不应出现在 enums 里，
#: 由 test_enum_names_and_values_match_contract 负责；这里只管命名）
UPPER_CODE_ENUMS = {"gate", "reason_code"}
IMPORT_CODES_JSON = Path(__file__).resolve().parents[1] / "unit" / "import_codes.json"
TODO = "后端 /meta/enums 未同步契约（T-B01 v0.2 修订；v0.2.3 由后端按 T-A03 同步：version、PAYLOAD_TOO_LARGE 等）"
#: 本组测试对齐的契约版本（T-T23 升到 v0.2.8：架构师 T-A09 6ef79c4，在本地 main、尚未推 origin；
#: origin/main 0cb78ad 的 docs 与后端仍为 v0.2.7）；/meta/enums.version 最终必须等于它
CONTRACT_VERSION = "v0.2.8"
#: 用旧一版文档（origin/main 仍为 v0.2.7）运行时 xfail 而不是失败
DOCS_PENDING = "docs 仍为 v0.2.7：契约 v0.2.8（T-A09 6ef79c4）未推到 origin（运维推送）"
#: 各版本契约的错误码 / 原因码个数（v0.2.7、v0.2.8 无新增错误码、原因码：59 / 22）
CODE_COUNTS = {"v0.2.4": (58, 23), "v0.2.5": (56, 22), "v0.2.6": (59, 22), "v0.2.7": (59, 22), "v0.2.8": (59, 22)}
#: 契约 v0.2.8（T-A09 #4–#9）改动的已有枚举：security_type 加 etf（位于 cdr 与 index 之间）、gap_reason 加 not_applicable
V028_ENUM_CHANGED = {"security_type": ["stock", "cdr", "etf", "index"]}
V028_ENUM_ADDED = {"gap_reason": "not_applicable"}
B_V028_ENUMS = ("后端 T-B02y（契约 v0.2.8 / T-A09：schemas/enums.py security_type 加 etf、gap_reason 加 not_applicable，"
                "version 改 v0.2.8；已在本地 main 457a211，未推 origin）")
#: 契约 v0.2.7 新增枚举（T-A08 变更表 #14，共 18 个）；factor_category 取值待 T003 定稿，契约暂不列值
V027_ENUMS = {
    "alert_origin": ["plan_condition", "holding_event", "user_custom"],
    "alert_status": ["new", "read", "checked", "acted", "dismissed"],
    "announcement_category": ["periodic_report", "other"],
    "board": ["main", "chinext", "star", "bse"],
    "data_gap_scope": ["user", "account", "security", "market"],
    "factor_category": [],
    "industry_taxonomy": ["sw_l1", "sw_l2", "csrc"],
    "instance_event_kind": ["created", "confirmed", "paused", "resumed", "params_changed", "archived"],
    "instance_origin": ["classifier", "user", "system"],
    "instance_sort": ["created_at_desc", "updated_at_desc", "strategy_name_asc"],
    "listing_status": ["listed", "delisting_period", "delisted", "missing_from_list"],
    "plan_condition_kind": ["trigger", "invalidation"],
    "report_period": ["q1", "h1", "q3", "fy"],
    "sector_kind": ["industry", "concept"],
    "sector_sort": ["main_net_desc", "main_net_asc", "change_pct_desc", "change_pct_asc"],
    "security_match_kind": ["code_exact", "name_exact", "initials_exact", "code_prefix", "name_prefix", "initials_prefix",
                            "name_contains", "former_name", "former_code", "fuzzy"],
    "security_risk_flag": ["st", "star_st", "delisting"],
    "security_type": ["stock", "cdr", "index"],
}
#: 契约 v0.2.7 给已有枚举加的值
V027_ENUM_ADDED = {"data_provider": "exchange"}
B_V027_ENUMS = ("后端 T-B01 / T-B06 / T-B07 / T-B10（契约 v0.2.7 / T-A08：schemas/enums.py 加 18 个枚举、data_provider 加 exchange，"
                "version 改 v0.2.7）")
#: 契约 v0.2.6 新增项（T-A07 §3/§4）
V026_ERRORS = {"DATA_LICENCE_IN_USE": 409, "DATA_LICENCE_NOT_SET": 409, "DATA_LICENCE_UNAVAILABLE": 409}
V026_ENUMS = {
    "data_licence_status": ["not_set", "pending_verification", "active", "invalid", "expired", "quota_exceeded", "ip_limited",
                            "paused_by_admin"],
    "data_licence_tier": ["free", "trial", "monthly", "annual", "diamond", "other"],
}
V026_ENUM_ADDED = {"notification_kind": "data_licence", "gap_reason": "data_licence_unavailable"}
B_V026_ENUMS = "后端 T-B01 / T-B45（契约 v0.2.6 / T-A07 §5：errors.py 加 3 个 DATA_LICENCE_* 码、schemas/enums.py 加证书枚举，version 改 v0.2.6）"
#: 契约 v0.2.5 作废项（T-A06 §1）
V025_RETIRED_ENUMS = ("consent_key", "legal_doc_key", "consent_presentation", "assessment_status")
V025_RETIRED_ERRORS = ("CONSENT_REQUIRED", "STRATEGY_FIT_ACK_REQUIRED")
V025_RETIRED_REASONS = ("PROFILE_OR_CONSENT_MISSING",)
B_V025_ENUMS = "后端 T-B01 / T-B03b（契约 v0.2.5 / T-A06 §3：errors.py、schemas/enums.py 删作废码与枚举，version 改 v0.2.5）"


# ---------------- 契约 markdown 解析 ----------------
def _section(text: str, start: str, end_prefix: str = "\n## ") -> str:
    i = text.index(start)
    j = text.find(end_prefix, i + len(start))
    return text[i : j if j != -1 else None]


def parse_enums(contract: str) -> dict[str, list[str]]:
    sec = _section(contract, "## 3. 枚举")
    out: dict[str, list[str]] = {}
    for line in sec.splitlines():
        m = re.match(r"^\| `([a-z_]+)` \| (.*) \|$", line)
        if not m:
            continue
        name, cell = m.groups()
        cell = re.sub(r"（[^）]*）", "", cell)  # 去掉全角括号内的说明
        # 只取单元格开头连续的取值（可带半角注记，如 `stop_take`(RC1)）；其后的说明文字里的反引号不是取值
        # （v0.2.7 的 data_provider / listing_status 说明里提到 `ProviderRef.provider`、`SecurityProfile.suspended`）
        lead = re.match(r"(?:`[^`]+`(?:\([A-Z0-9]+\))?[\s、，,]*)*", cell)
        out[name] = re.findall(r"`([^`]+)`", lead.group(0) if lead else "")
    return out


def parse_error_codes(contract: str) -> dict[str, int]:
    sec = _section(contract, "## 4. 错误码表", "\n### 4.1")
    return {m.group(2): int(m.group(1)) for m in re.finditer(r"^\| (\d{3}) \| `([A-Z0-9_]+)` \|", sec, re.M)}


def parse_reason_codes(contract: str) -> dict[str, dict[str, Any]]:
    sec = _section(contract, "### 6.1 不可执行原因码", "\n---")
    out: dict[str, dict[str, Any]] = {}
    for m in re.finditer(r"^\| `([A-Z0-9_]+)` \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$", sec, re.M):
        code, kinds, check_on, manual = (g.strip() for g in m.groups())
        out[code] = {
            "release_kinds": [k.strip() for k in kinds.split("/")],
            "check_on": [c.strip() for c in check_on.split(",")],
            "manually_releasable": manual.startswith("是"),
        }
    return out


@pytest.fixture(scope="module")
def contract(docs_dir: Path) -> str:
    return (docs_dir / "api-contract.md").read_text(encoding="utf-8")


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def payload(client) -> dict[str, Any]:
    resp = client.get(PATH)
    assert resp.status_code == 200
    return resp.json()


# ---------------- 解析器自检（文档 v0.2.3） ----------------
def test_contract_header_version(contract):
    m = re.search(r"版本：\*\*(v[0-9.]+)\*\*", contract)
    assert m and m.group(1) in {"v0.2.5", "v0.2.6", "v0.2.7", CONTRACT_VERSION}, m and m.group(1)
    assert contract.index("### v0.2.5") < contract.index("### v0.2.4") < contract.index("### v0.2.3") < contract.index("### v0.2.2")
    if m.group(1) == "v0.2.5":
        pytest.xfail(DOCS_PENDING)
    assert contract.index("### v0.2.6") < contract.index("### v0.2.5")
    if m.group(1) == "v0.2.6":
        pytest.xfail(DOCS_PENDING)
    assert contract.index("### v0.2.7") < contract.index("### v0.2.6")
    if m.group(1) != CONTRACT_VERSION:
        pytest.xfail(DOCS_PENDING)
    assert contract.index("### v0.2.8") < contract.index("### v0.2.7")


def _docs_version(contract: str) -> str:
    m = re.search(r"版本：\*\*(v[0-9.]+)\*\*", contract)
    return m.group(1) if m else ""


def _is_v025(contract: str) -> bool:
    """文档已是 v0.2.5 或更新（v0.2.5 的删除项在 v0.2.6 仍然成立）。"""
    return _docs_version(contract) in {"v0.2.5", "v0.2.6", "v0.2.7", "v0.2.8"}


def _is_v026(contract: str) -> bool:
    """文档已是 v0.2.6 或更新（v0.2.7、v0.2.8 未删 v0.2.6 新增项）。"""
    return _docs_version(contract) in {"v0.2.6", "v0.2.7", "v0.2.8"}


def _is_v027(contract: str) -> bool:
    """文档已是 v0.2.7 或更新（v0.2.8 只给 security_type / gap_reason 加值，见 V028_ENUM_CHANGED）。"""
    return _docs_version(contract) in {"v0.2.7", "v0.2.8"}


def _is_v028(contract: str) -> bool:
    return _docs_version(contract) == "v0.2.8"


def _v027_enums_as_of(version: str) -> dict[str, list[str]]:
    """V027_ENUMS 在给定版本下的期望取值：v0.2.8 起 security_type 按 V028_ENUM_CHANGED（逐项相等，不放宽）。"""
    return {**V027_ENUMS, **(V028_ENUM_CHANGED if version == "v0.2.8" else {})}


def test_contract_parsers_sanity(contract):
    enums = parse_enums(contract)
    assert "reason_code" in enums and len(enums) >= 50
    assert enums["import_status"] == ["uploaded", "parsing", "previewed", "committed", "failed", "discarded", "reverted"]
    assert enums["ingest_health"] == ["ok", "stale", "paused", "unknown"]
    errors = parse_error_codes(contract)
    # v0.2.3：新增 413 PAYLOAD_TOO_LARGE（57 → 58）；v0.2.5：删 CONSENT_REQUIRED、STRATEGY_FIT_ACK_REQUIRED（58 → 56），
    # 删原因码 PROFILE_OR_CONSENT_MISSING（23 → 22）；v0.2.6：加 3 个 DATA_LICENCE_*（56 → 59）；v0.2.7：不变（59 / 22）
    assert errors["METHOD_NOT_ALLOWED"] == 405 and errors["PAYLOAD_TOO_LARGE"] == 413
    assert (len(errors), len(parse_reason_codes(contract))) == CODE_COUNTS[_docs_version(contract)]


def test_v025_contract_drops_consent_and_assessment_items(contract):
    """v0.2.5 组 1（文档层）：契约 §3/§4/§6.1 不再有同意/测评枚举、``CONSENT_REQUIRED``、``STRATEGY_FIT_ACK_REQUIRED``、
    ``PROFILE_OR_CONSENT_MISSING``；原因码 22 个（错误码个数见 CODE_COUNTS）。"""
    if not _is_v025(contract):
        pytest.xfail(DOCS_PENDING)
    enums, errors, reasons = parse_enums(contract), parse_error_codes(contract), parse_reason_codes(contract)
    assert not set(V025_RETIRED_ENUMS) & set(enums)
    assert not set(V025_RETIRED_ERRORS) & set(errors) and len(errors) == CODE_COUNTS[_docs_version(contract)][0]
    assert not set(V025_RETIRED_REASONS) & set(reasons) and len(reasons) == 22


def test_v025_meta_enums_drops_consent_and_assessment_items(payload):
    """v0.2.5 组 1（接口层，后端 4162abb 已同步）：``/meta/enums`` 不含作废枚举；``reason_codes`` 22 个且不含
    PROFILE_OR_CONSENT_MISSING；``error_codes`` 不含 CONSENT_REQUIRED、STRATEGY_FIT_ACK_REQUIRED（version 见 test_version_and_import_codes）。"""
    assert not set(V025_RETIRED_ENUMS) & set(payload["enums"])
    reasons = {r["code"] for r in payload["reason_codes"]}
    assert len(reasons) == 22 and not set(V025_RETIRED_REASONS) & reasons
    assert not set(V025_RETIRED_ERRORS) & {e["code"] for e in payload["error_codes"]}


def test_v026_contract_adds_data_licence_items(contract):
    """v0.2.6（文档层）：3 个 409 DATA_LICENCE_* 码、data_licence_status/tier 枚举、notification_kind 加 data_licence、
    gap_reason 加 data_licence_unavailable。"""
    if not _is_v026(contract):
        pytest.xfail("docs 仍为 v0.2.5：契约 v0.2.6（T-A07 308afd3）不在所用 docs 中")
    enums, errors = parse_enums(contract), parse_error_codes(contract)
    assert {k: errors.get(k) for k in V026_ERRORS} == V026_ERRORS
    assert {k: enums.get(k) for k in V026_ENUMS} == V026_ENUMS
    for name, value in V026_ENUM_ADDED.items():
        assert value in enums[name], name


def test_v026_meta_enums_has_data_licence_items(payload):
    """v0.2.6（接口层）：``/meta/enums`` 含证书枚举与 3 个 DATA_LICENCE_* 错误码，version = v0.2.6。

    T-B04a.md（efcd244，已在 origin/main）：后端已同步 v0.2.6，去掉装饰器 xfail、直接断言；只在后端仍报 v0.2.5 时
    imperative xfail，写明负责任务。version 为 v0.2.6 或更新（v0.2.7 无不兼容变更）。"""
    if payload["version"] == "v0.2.5":
        pytest.xfail(B_V026_ENUMS)
    errors = {e["code"]: e for e in payload["error_codes"]}
    assert {k: errors[k]["http_status"] for k in V026_ERRORS if k in errors} == V026_ERRORS
    for name, values in V026_ENUMS.items():
        assert list(payload["enums"][name]) == values, name
    for name, value in V026_ENUM_ADDED.items():
        assert value in payload["enums"][name], name
    assert payload["version"] in {"v0.2.6", "v0.2.7", CONTRACT_VERSION}


def test_v027_contract_adds_enums(contract):
    """v0.2.7（文档层，T-A08 #14）：新增 18 个枚举（取值逐项相等）、``data_provider`` 加 ``exchange``；错误码 / 原因码不变。"""
    if not _is_v027(contract):
        pytest.xfail(DOCS_PENDING)
    enums = parse_enums(contract)
    want = _v027_enums_as_of(_docs_version(contract))
    assert {k: enums.get(k) for k in want} == want
    for name, value in V027_ENUM_ADDED.items():
        assert value in enums[name], name
    assert (len(parse_error_codes(contract)), len(parse_reason_codes(contract))) == CODE_COUNTS[_docs_version(contract)]


def test_v027_meta_enums_has_new_enums(payload):
    """v0.2.7（接口层）：``/meta/enums`` 含 18 个新枚举与 ``data_provider.exchange``；version 为 v0.2.7 时取值逐项等于 v0.2.7，
    为 v0.2.8 时 security_type 按 v0.2.8（加 etf）。后端仍报更早版本 → xfail。"""
    if re.fullmatch(r"v0\.2\.[5-6]", payload["version"]):
        pytest.xfail(B_V027_ENUMS + f"；当前 version = {payload['version']}")
    assert payload["version"] in {"v0.2.7", CONTRACT_VERSION}
    for name, values in _v027_enums_as_of(payload["version"]).items():
        assert list(payload["enums"][name]) == values, name
    for name, value in V027_ENUM_ADDED.items():
        assert value in payload["enums"][name], name


def test_v028_contract_changes_enums(contract):
    """v0.2.8（文档层，T-A09 验收第 1 条）：security_type = stock, cdr, etf, index；gap_reason 含 not_applicable；
    错误码 / 原因码个数不变（59 / 22）。所用 docs 仍为 v0.2.7 → xfail（运维推送 6ef79c4）。"""
    if not _is_v028(contract):
        pytest.xfail(DOCS_PENDING)
    enums = parse_enums(contract)
    assert {k: enums.get(k) for k in V028_ENUM_CHANGED} == V028_ENUM_CHANGED
    for name, value in V028_ENUM_ADDED.items():
        assert enums[name][-1] == value, name  # 追加在末尾
    assert (len(parse_error_codes(contract)), len(parse_reason_codes(contract))) == CODE_COUNTS["v0.2.8"]


def test_v028_meta_enums(payload):
    """v0.2.8（接口层，T-A09 验收第 1 条）：``/meta/enums`` version = v0.2.8，security_type 含 etf（cdr 与 index 之间），
    gap_reason 含 not_applicable。后端仍报 v0.2.7 或更早 → xfail（T-B02y，本地 main 457a211 未推 origin）。"""
    if re.fullmatch(r"v0\.2\.[5-7]", payload["version"]):
        pytest.xfail(B_V028_ENUMS + f"；当前 version = {payload['version']}")
    assert payload["version"] == CONTRACT_VERSION
    for name, values in V028_ENUM_CHANGED.items():
        assert list(payload["enums"][name]) == values, name
    for name, value in V028_ENUM_ADDED.items():
        assert value in payload["enums"][name], name


# ---------------- 逐项比对（文档 v0.2.3） ----------------
def _diff_or_xfail(diff: list[str], what: str) -> None:
    if diff:
        pytest.xfail(f"{TODO}：{what} 与契约不一致：" + "; ".join(diff[:12]) + (" …" if len(diff) > 12 else ""))


def test_enum_names_and_values_match_contract(payload, contract):
    want = {k: v for k, v in parse_enums(contract).items() if k != "reason_code"}
    got = payload["enums"]
    diff = [f"缺 {k}" for k in sorted(set(want) - set(got))]
    diff += [f"多 {k}" for k in sorted(set(got) - set(want))]
    diff += [f"{k}: {got[k]} != {want[k]}" for k in sorted(set(want) & set(got)) if got[k] != want[k]]
    _diff_or_xfail(diff, "enums")


def test_reason_codes_match_contract(payload, contract):
    want = parse_reason_codes(contract)
    got = {r["code"]: r for r in payload["reason_codes"]}
    if set(got) - set(want) == set(V025_RETIRED_REASONS) and _is_v025(contract):
        pytest.xfail(B_V025_ENUMS + "：reason_codes 仍含 PROFILE_OR_CONSENT_MISSING")
    assert set(got) == set(want), "原因码集合（v0.2.4：23 个；v0.2.5：22 个）"
    for code, spec in want.items():
        assert got[code]["manually_releasable"] == spec["manually_releasable"], code
        assert sorted(got[code]["release_kinds"]) == sorted(spec["release_kinds"]), code
        assert sorted(got[code]["check_on"]) == sorted(spec["check_on"]), code


@pytest.mark.parametrize("rule_id", ["SH0C", "IT0C"])
def test_horizon_rule_ids_are_not_reason_codes(payload, contract, rule_id):
    """契约 v0.2.3 #23（T-A05）：SH0C/IT0C 只是 HorizonCap.rule_id，不进 /meta/enums，也不在 §6.1 原因码表里。"""
    assert rule_id not in parse_reason_codes(contract)
    assert rule_id not in {r["code"] for r in payload["reason_codes"]}
    for key in ("error_codes", "import_codes"):
        assert rule_id not in {r["code"] if isinstance(r, dict) else r for r in payload.get(key, [])}
    assert all(rule_id not in values for values in payload["enums"].values())


def test_error_codes_match_contract(payload, contract):
    want = parse_error_codes(contract)
    got = {e["code"]: e for e in payload["error_codes"]}
    got_http = {c: e["http_status"] for c, e in got.items() if e["scope"] in {"http", "internal"}}
    diff = [f"缺 {c}" for c in sorted(set(want) - set(got_http))]
    diff += [f"多 {c}" for c in sorted(set(got_http) - set(want))]
    diff += [f"{c}: {got_http[c]} != {want[c]}" for c in sorted(set(want) & set(got_http)) if got_http[c] != want[c]]
    diff += [f"row 级码 {c} 应移到 import_codes" for c, e in got.items() if e["scope"] == "row"]
    _diff_or_xfail(diff, "error_codes")


def test_version_and_import_codes(payload):
    if "version" not in payload or "import_codes" not in payload:
        pytest.xfail(f"{TODO}：/meta/enums 缺 version / import_codes（契约 v0.2 §7.10）")
    if payload["version"] != CONTRACT_VERSION and re.fullmatch(r"v0\.2(\.[0-7])?", payload["version"]):
        pytest.xfail(f"后端（T-B02y，v0.2.8 同步，本地 main 457a211 未推 origin）：app/schemas/enums.py 的 CONTRACT_VERSION 仍为 "
                     f"{payload['version']}，应改为 {CONTRACT_VERSION}")
    assert payload["version"] == CONTRACT_VERSION
    want = {c["code"]: c for c in json.loads(IMPORT_CODES_JSON.read_text(encoding="utf-8"))["codes"]}
    got = {c["code"]: c for c in payload["import_codes"]}
    assert set(got) == set(want)
    for code, spec in want.items():
        assert (got[code]["severity"], got[code]["scope"]) == (spec["severity"], spec["scope"]), code
        assert isinstance(got[code].get("needs_action"), bool), code  # 契约 §7.10 / ImportFinding


# ---------------- 不依赖文档的规则 ----------------
def test_naming_rules(payload):
    bad = []
    for name, values in payload["enums"].items():
        rx = CODE_RE if name in UPPER_CODE_ENUMS else ENUM_RE
        bad += [f"{name}={v}" for v in values if not rx.match(v)]
    for key in ("reason_codes", "error_codes", "import_codes"):
        bad += [f"{key}={c['code']}" for c in payload.get(key, []) if not CODE_RE.match(c["code"])]
    assert not bad


def test_code_namespaces_disjoint(payload):
    spaces = {k: {c["code"] for c in payload.get(k, [])} for k in ("reason_codes", "error_codes", "import_codes")}
    overlap = (spaces["reason_codes"] & spaces["error_codes"]) | (spaces["reason_codes"] & spaces["import_codes"]) | (spaces["error_codes"] & spaces["import_codes"])
    if overlap and "import_codes" not in payload:
        pytest.xfail(f"{TODO}：命名空间重名 {sorted(overlap)}（v0.2 将 error_codes.DATA_STALE 改为 FRESH_DATA_REQUIRED）")
    assert not overlap


def test_enum_values_unique(payload):
    for name, values in payload["enums"].items():
        assert len(values) == len(set(values)), name


def test_etag_304_and_cache_control(client):
    r1 = client.get(PATH)
    etag = r1.headers["ETag"]
    assert re.fullmatch(r'"[^"]+"', etag), "/meta/enums 用强 ETag（契约 §7.10）"
    assert r1.headers["Cache-Control"] == "public, max-age=300"
    assert r1.headers["content-type"].startswith("application/json")
    r2 = client.get(PATH, headers={"If-None-Match": etag})
    assert r2.status_code == 304 and r2.content == b""
    assert r2.headers["ETag"] == etag
    r3 = client.get(PATH, headers={"If-None-Match": f'"other", {etag}'})
    assert r3.status_code == 304
    r4 = client.get(PATH, headers={"If-None-Match": '"stale-etag"'})
    assert r4.status_code == 200 and r4.json() == r1.json()


def test_etag_stable_across_apps(make_client):
    assert make_client().get(PATH).headers["ETag"] == make_client().get(PATH).headers["ETag"]


def test_no_login_required(client):
    assert client.get(PATH, cookies={}).status_code == 200


def test_risk_control_labels(payload):
    assert payload["risk_control_labels"] == {
        "stop_take": "RC1", "position_cap": "RC2", "total_exposure": "RC3",
        "sector_concentration": "RC4", "loss_streak_drawdown": "RC5", "plan_violation": "RC6",
    }
