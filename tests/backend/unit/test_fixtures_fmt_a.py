"""fmt_a 合成交割单夹具的完整性守卫（T-T01；T-T01a 增补 CR 换行、fake_identifiers、expected.json）。

覆盖 plan §3.5A 对 tests/fixtures/broker_statements/ 的要求：
- 每个数据文件都登记在 meta.json，且 sha256 / 字节数 / 编码 / 换行与登记一致；
- `# SYNTHETIC` 标记存在（meta.json 首键、generate.py 第 2 行、README 第 1 行）；
- `generate.py --check` 通过（派生夹具可由生成器逐字节重建）；
- 泄漏标记检查：S5/S6（plan 7.4A）命中只允许 meta.json.fake_identifiers 中的虚构值，且逐文件命中次数与登记一致；
  不出现未登记文件。断言失败时只报文件名与个数，不回显命中值。

本模块不读取 /workspace/team/samples 下的原始范本（原始值永不进入仓库或测试）。
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

FMT_A = Path(__file__).resolve().parents[2] / "fixtures" / "broker_statements" / "fmt_a"
META = json.loads((FMT_A / "meta.json").read_text(encoding="utf-8"))
ENTRIES = {e["file"]: e for e in META["files"]}
NON_DATA_FILES = {"README.md", "meta.json", "generate.py", "expected.json"}

FAKE = META["fake_identifiers_detail"]
FAKE_VALUES = {e["value"] for k in ("shareholder_codes", "seat_codes") for e in FAKE[k]}
# 夹具中允许出现的虚构股东代码样式值（来自 meta.json.fake_identifiers）；其他任何 [A-Z]\d{9} 命中都视为疑似泄漏。
ALLOWED_SHAREHOLDER_LIKE = {v.encode() for v in FAKE_VALUES}
SHAREHOLDER_RE = re.compile(rb"[A-Z]\d{9}")
# plan 7.4A（ASCII 语义的 \b，与 gitleaks/RE2 相同）
RULE_S5 = re.compile(r"\b[A-Z]\d{9}\b", re.ASCII)
RULE_S6 = re.compile(r"\b0\d{9}\b", re.ASCII)


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_marker_present_everywhere() -> None:
    assert next(iter(META)) == "marker"
    assert META["marker"] == "# SYNTHETIC"
    assert META["synthetic"] is True
    assert META["format"] == "fmt_a"
    gen_lines = (FMT_A / "generate.py").read_text(encoding="utf-8").splitlines()
    assert gen_lines[1] == "# SYNTHETIC"
    readme_first = (FMT_A / "README.md").read_text(encoding="utf-8").splitlines()[0]
    assert readme_first.strip() == "# SYNTHETIC"


def test_every_file_is_registered() -> None:
    on_disk = {p.name for p in FMT_A.iterdir() if p.is_file()}
    unregistered = on_disk - NON_DATA_FILES - set(ENTRIES)
    missing = set(ENTRIES) - on_disk
    assert not unregistered, f"未在 meta.json 登记的文件：{sorted(unregistered)}"
    assert not missing, f"meta.json 登记但不存在：{sorted(missing)}"
    assert all(e["synthetic"] is True for e in ENTRIES.values())


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_meta_sha256_and_size(name: str) -> None:
    entry = ENTRIES[name]
    path = FMT_A / name
    assert path.stat().st_size == entry["bytes"]
    assert _sha256(path) == entry["sha256"]


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_line_endings_match_meta(name: str) -> None:
    data = (FMT_A / name).read_bytes()
    crlf = data.count(b"\r\n")
    lone_lf = data.count(b"\n") - crlf
    expected = ENTRIES[name]["line_ending"]
    if expected is None:  # 空文件
        assert data == b""
    elif expected.startswith("CRLF"):
        assert lone_lf == 0 and crlf > 0
        # "CRLF（末行无换行）"：最后一行没有换行符
        assert data.endswith(b"\r\n") is ("末行无换行" not in expected)
    elif expected == "LF":
        assert crlf == 0 and lone_lf > 0
    elif expected == "CR":  # 仅 CR（老式 Mac），T-T01a
        assert b"\n" not in data and data.count(b"\r") == ENTRIES[name]["physical_lines"]
    else:
        pytest.fail(f"meta.json 中未知的 line_ending：{expected!r}")


# 唯一"故意解码失败"的夹具：末行截断在双字节字符中间（TC-ENC-06）
EXPECTED_DECODE_FAILURE = {"trades_truncated_mid_char.txt"}


@pytest.mark.parametrize("name", sorted(n for n, e in ENTRIES.items() if e["encoding"]))
def test_strict_decode_matches_meta_encoding(name: str) -> None:
    data = (FMT_A / name).read_bytes()
    encoding = ENTRIES[name]["encoding"]
    if name in EXPECTED_DECODE_FAILURE:
        with pytest.raises(UnicodeDecodeError):
            data.decode(encoding)
    else:
        data.decode(encoding)


def test_generate_check_passes() -> None:
    proc = subprocess.run(
        [sys.executable, str(FMT_A / "generate.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_generate_out_is_byte_identical(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(FMT_A / "generate.py"), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    produced = sorted(p.name for p in tmp_path.iterdir() if p.is_file() and p.name != "meta.json")
    assert produced, "generate.py --out 未产出文件"
    for name in produced:
        assert (tmp_path / name).read_bytes() == (FMT_A / name).read_bytes(), name


def test_no_unexpected_shareholder_like_codes() -> None:
    hits: dict[str, set[bytes]] = {}
    for p in sorted(FMT_A.iterdir()):
        if not p.is_file():
            continue
        found = set(SHAREHOLDER_RE.findall(p.read_bytes())) - ALLOWED_SHAREHOLDER_LIKE
        if found:
            hits[p.name] = found
    # 只报告文件名和命中数，不回显命中值本身
    assert not hits, {k: len(v) for k, v in hits.items()}


def test_main_fixtures_decode_as_strict_gbk() -> None:
    for name in ("trades_sample.txt", "positions_sample.txt"):
        assert ENTRIES[name]["encoding"].lower() in {"gbk", "gb18030"}
        (FMT_A / name).read_bytes().decode("gbk")  # 严格模式，失败即抛异常


# ---------------- T-T01a：fake_identifiers（S5/S6 豁免集合） ----------------
def _lines(name: str) -> list[str]:
    data = (FMT_A / name).read_bytes()
    enc = ENTRIES[name]["encoding"] or "gbk"
    text = data.decode(enc, errors="replace") if data else ""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _scan(name: str) -> dict[str, dict[str, int]]:
    lines = _lines(name)
    header_has = any("股东" in line for line in lines[:6])
    hits: dict[str, dict[str, int]] = {"S5": {}, "S6": {}}
    for line in lines:
        for m in RULE_S5.findall(line):
            hits["S5"][m] = hits["S5"].get(m, 0) + 1
        if header_has or "股东" in line:
            for m in RULE_S6.findall(line):
                hits["S6"][m] = hits["S6"].get(m, 0) + 1
    return hits


def test_fake_identifiers_flat_list_for_ci() -> None:
    """plan 7.4A 条件 5 与 scripts/ci（check_fixtures.py、secret_scan.py）：顶层 fake_identifiers 是字符串扁平列表。"""
    flat = META["fake_identifiers"]
    assert isinstance(flat, list) and all(isinstance(v, str) for v in flat)
    assert flat == sorted(FAKE_VALUES)


def test_fake_identifiers_shape() -> None:
    assert set(FAKE) >= {"description", "rules", "shareholder_codes", "seat_codes", "by_file"}
    assert len(FAKE["shareholder_codes"]) == 2 and len(FAKE["seat_codes"]) == 2
    for group in ("shareholder_codes", "seat_codes"):
        for e in FAKE[group]:
            assert re.fullmatch(e["format"], e["value"]), (group, e["market"])
            assert e["market"] in {"SH", "SZ"}
    assert set(FAKE["by_file"]) <= set(ENTRIES)


def test_fake_identifiers_come_from_generate_constants() -> None:
    """豁免值必须是 generate.py 中的常量（不从文件内容推导）。"""
    src = (FMT_A / "generate.py").read_text(encoding="utf-8")
    for v in FAKE_VALUES:
        assert f'"{v}"' in src


@pytest.mark.parametrize("name", sorted(n for n in ENTRIES if n.endswith(".txt")))
def test_s5_s6_hits_are_registered_fakes(name: str) -> None:
    hits = _scan(name)
    unknown = sum(1 for rule in hits.values() for v in rule if v not in FAKE_VALUES)
    assert unknown == 0, f"{name}: {unknown} 个 S5/S6 命中不在 fake_identifiers 中"
    reg = FAKE["by_file"].get(name, {"S5": {"values": [], "count": 0}, "S6": {"values": [], "count": 0}})
    for rule in ("S5", "S6"):
        assert sorted(hits[rule]) == reg[rule]["values"], (name, rule)
        assert sum(hits[rule].values()) == reg[rule]["count"], (name, rule)


def test_fake_identifiers_cover_cr_fixture() -> None:
    assert FAKE["by_file"]["trades_cr.txt"]["S5"]["count"] == FAKE["by_file"]["trades_lf.txt"]["S5"]["count"]


# ---------------- T-T01a：CR 夹具 ----------------
def test_cr_fixture_equals_lf_fixture_modulo_eol() -> None:
    cr = (FMT_A / "trades_cr.txt").read_bytes()
    lf = (FMT_A / "trades_lf.txt").read_bytes()
    assert cr.replace(b"\r", b"\n") == lf
    assert ENTRIES["trades_cr.txt"]["data_lines"] == ENTRIES["trades_lf.txt"]["data_lines"] == 5
    assert ENTRIES["trades_cr.txt"]["physical_lines"] == ENTRIES["trades_lf.txt"]["physical_lines"]


def test_expected_json_marker() -> None:
    exp = json.loads((FMT_A / "expected.json").read_text(encoding="utf-8"))
    assert exp["marker"] == "# SYNTHETIC"
    assert set(exp["files"]) == set(ENTRIES)


def test_readme_table_matches_meta() -> None:
    """README §3 文件清单中的字节数与 sha256 与 meta.json 一致（README §6 已改为引用 expected.json）。"""
    readme = (FMT_A / "README.md").read_text(encoding="utf-8")
    for name, e in ENTRIES.items():
        row = next((line for line in readme.splitlines() if line.startswith(f"| `{name}` |")), None)
        assert row is not None, f"README §3 缺少 {name}"
        assert f"| {e['bytes']} |" in row and e["sha256"] in row, name
    assert "expected.json" in readme.split("## 6.")[1].split("## 7.")[0]


# ---------------- T-T25（裁定 R7）：同一证券代码在全部夹具中只有一个名称 ----------------
#: 有意构造的损坏夹具（列错位：名称内插入空格；截断在半个汉字处），名称本身不完整，不参与本检查。
_NAME_CHECK_EXCLUDED = {"trades_column_mismatch.txt", "trades_truncated_mid_char.txt"}
_TRADE_ROW = re.compile(r"^\s*\d{8}\s+\d+\s+(\d{6})\s+(\S+)")
_POSITION_ROW = re.compile(r"^(\d{6})\s+(\S+)")


def _code_names() -> dict[str, dict[str, set[str]]]:
    seen: dict[str, dict[str, set[str]]] = {}
    for name, entry in ENTRIES.items():
        if name in _NAME_CHECK_EXCLUDED or not (FMT_A / name).read_bytes():
            continue
        rx = _POSITION_ROW if entry["kind"] == "positions" else _TRADE_ROW
        for line in _lines(name):
            m = rx.match(line)
            if m:
                seen.setdefault(m.group(1), {}).setdefault(m.group(2), set()).add(name)
    return seen


def test_r7_one_name_per_security_code_across_fixtures() -> None:
    """裁定 R7：gb18030 夹具曾把 600001 写成另一个名称，导致 security_master=all_fixture_codes 无法同时满足。
    断言失败时只报代码与文件名（代码与名称都是虚构值）。"""
    seen = _code_names()
    assert seen, "没有解析到任何数据行，检查正则"
    multi = {code: {n: sorted(f) for n, f in names.items()} for code, names in seen.items() if len(names) > 1}
    assert not multi, multi


def test_r7_gb18030_fixture_uses_its_own_code() -> None:
    seen = _code_names()
    owners = [code for code, names in seen.items() if any("\u4dae" in n for n in names)]
    assert owners == ["600004"], owners
    assert "trades_gb18030_ext_char.txt" not in {f for f in seen.get("600001", {}).get("示例甲业", set())}
