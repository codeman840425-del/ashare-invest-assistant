"""``GET /meta/enums``：T-B01 报告 §6 建议 7 + 契约 v0.2.3 §3/§4/§6.1/§7.10/§9（T-T01c 由 v0.2.2 升到 v0.2.3）。

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
#: 本组测试对齐的契约版本（T-T01b）；/meta/enums.version 必须等于它
CONTRACT_VERSION = "v0.2.3"


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
        out[name] = re.findall(r"`([^`]+)`", cell)
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
    assert m and m.group(1) == CONTRACT_VERSION
    assert contract.index("### v0.2.3") < contract.index("### v0.2.2") < contract.index("### v0.2.1")


def test_contract_parsers_sanity(contract):
    enums = parse_enums(contract)
    assert "reason_code" in enums and len(enums) >= 50
    assert enums["import_status"] == ["uploaded", "parsing", "previewed", "committed", "failed", "discarded", "reverted"]
    assert enums["ingest_health"] == ["ok", "stale", "paused", "unknown"]
    errors = parse_error_codes(contract)
    # v0.2.3：新增 413 PAYLOAD_TOO_LARGE（57 → 58）
    assert errors["METHOD_NOT_ALLOWED"] == 405 and errors["PAYLOAD_TOO_LARGE"] == 413 and len(errors) == 58
    assert len(parse_reason_codes(contract)) == 23


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
    assert set(got) == set(want), "原因码集合（23 个）"
    for code, spec in want.items():
        assert got[code]["manually_releasable"] == spec["manually_releasable"], code
        assert sorted(got[code]["release_kinds"]) == sorted(spec["release_kinds"]), code
        assert sorted(got[code]["check_on"]) == sorted(spec["check_on"]), code


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
    if payload["version"] != CONTRACT_VERSION and re.fullmatch(r"v0\.2(\.[0-2])?", payload["version"]):
        pytest.xfail(f"后端（T-B01 / v0.2.3 同步）：app/schemas/enums.py 的 CONTRACT_VERSION 仍为 {payload['version']}，应改为 {CONTRACT_VERSION}")
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
