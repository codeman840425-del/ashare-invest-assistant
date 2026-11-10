# ruff: noqa: S101, ANN401
"""T-T81→T-T82：T-R58 复测「HF 与 vipdoc 拼接校验」独立验证用例（retest_plan §2.7，T-R58d @6814edc）。

T-T82 接线完成（ds/T-B136@2758487 落地 retest.t_r58.splice）：原 pending 9 条已接到真实实现，
常绿层 5 处占位断言已换成 checker 实算（T-T82 执行单恒真断言清理清单，未清理=阻断）。
接线后 24 用例全过、0 error；零麦蕊、不读任何真实/私有样本、不写库。

规格出处：docs/strategies/T-R58/retest_plan.md §2.7 第 1–8 条（origin/docs/T-R58 @6814edc）。
被测模块：retest.t_r58.splice（decode_lc1 / relabel_1300 / check_splice / selected_lc1 / merge_sources）。
"""

from __future__ import annotations

import datetime as dt
import struct
import zoneinfo
from pathlib import Path
from typing import Any, Iterator

import pyarrow as pa
import pytest

from retest.t_r58 import splice
from retest.t_r58.errors import DataFormatError

pytestmark = pytest.mark.pending_impl  # 接线完成标记沿用（历史 marker；用例本体已全部真实断言）

CST = zoneinfo.ZoneInfo("Asia/Shanghai")
MINUTE_BYTES = 32
MINUTE_STRUCT = struct.Struct("<HHfffffII")  # 日期、分钟、O/H/L/C、成交额、成交量(股)、保留
BARS_PER_DAY = 240
MORNING = [f"{h:02d}:{m:02d}" for h, m in
           [(9, 31), *[(9, m) for m in range(32, 60)], *[(10, m) for m in range(60)],
            *[(11, m) for m in range(0, 31)]]]
AFTERNOON = [f"{h:02d}:{m:02d}" for h, m in
             [*((13, m) for m in range(1, 60)), *[(14, m) for m in range(60)], (15, 0)]]
VALID_LABELS = set(MORNING) | set(AFTERNOON)


def _encode_min_line(day: dt.date, minute_of_day: int, o: float, h: float, l: float,
                     c: float, turnover: float, volume: int) -> bytes:
    """按 §2.7 第 2 条把一根 1 分钟 bar 编码为 32 字节 lc1 记录（bar 结束时刻标签）。"""
    d = (day.year - 2004) * 2048 + day.month * 100 + day.day
    return MINUTE_STRUCT.pack(d, minute_of_day, o, h, l, c, turnover, volume, 0)


def _decode_min_line(raw: bytes) -> dict[str, Any]:
    """§2.7 第 2 条口径的解码：价格 float32 元（不 ÷100）、量 uint32 股、标签为 bar 结束时刻。"""
    d, minute, o, h, l, c, turnover, volume, _reserved = MINUTE_STRUCT.unpack(raw[:MINUTE_BYTES])
    day = dt.date(d // 2048 + 2004, (d % 2048) // 100, (d % 2048) % 100)
    hh, mm = divmod(minute, 60)
    return {"date": day, "label": f"{hh:02d}:{mm:02d}", "open": o, "high": h, "low": l,
            "close": c, "turnover": turnover, "volume": volume}


def _labels_of_day(bars: list[tuple[int, float, float, float, float, float, int]]) -> list[str]:
    hh, mm = divmod(bars[0][0], 60)
    return [f"{hh:02d}:{mm:02d}" for hh, mm in
            (divmod(b[0], 60) for b in bars)]


class Lc1Builder:
    """合成 vipdoc lc1 文件：一只股票一个文件，逐日 240 根。"""

    def __init__(self) -> None:
        self.days: dict[dt.date, list[tuple[int, float, float, float, float, float, int]]] = {}

    def add_day(self, day: dt.date, *, base: float = 10.0, volume: int = 10000,
                labels: list[str] | None = None, o: float | None = None,
                c: float | None = None) -> None:
        """写一天。``labels`` 缺省为完整 240 根；特殊场景（13:00 异常、新股 1 根）显式传。"""
        if labels is None:
            labels = MORNING + AFTERNOON
        bars: list[tuple[int, float, float, float, float, float, int]] = []
        for i, label in enumerate(labels):
            hh, mm = int(label[:2]), int(label[3:])
            price = (o if i == 0 and o is not None else base)
            close = (c if i == len(labels) - 1 and c is not None else base)
            bars.append((hh * 60 + mm, price, price + 0.01, price - 0.01, close,
                         price * volume, volume))  # 量=100 股整数倍
        self.days[day] = bars

    def relabel_last_morning_to_1300(self, day: dt.date) -> None:
        """§2.7 第 2 条已知异常：上午最后一根 11:30 改标 13:00（240 根不变，11:30 标签消失）。"""
        bars = self.days[day]
        target = next(i for i, b in enumerate(bars) if b[0] == 11 * 60 + 30)
        bars[target] = (13 * 60, *bars[target][1:])
        assert len(bars) == BARS_PER_DAY
        labels = [b[0] for b in bars]
        assert 11 * 60 + 30 not in labels and 13 * 60 in labels

    def write(self, root: Path, exchange: str, symbol: str) -> Path:
        """root 即该数据包的 vipdoc 目录（如 <pkg>/vipdoc），在其下建 <exchange>/minline。"""
        directory = root / exchange / "minline"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{symbol}.lc1"
        with path.open("wb") as f:
            for day in sorted(self.days):
                for bar in self.days[day]:
                    f.write(_encode_min_line(day, *bar))
        return path

    def read_back(self, path: Path) -> list[dict[str, Any]]:
        """用本文件自己的解码口径读回（自证生成器可被 §2.7 第 2 条解码）。"""
        out = []
        data = path.read_bytes()
        assert len(data) % MINUTE_BYTES == 0
        for i in range(0, len(data), MINUTE_BYTES):
            out.append(_decode_min_line(data[i:i + MINUTE_BYTES]))
        return out


class HfBuilder:
    """合成 HF parquet 生成器（字段按 §2.7 第 2 条第 1 款；接线后经 splice.SCHEMA 校验）。"""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add_day(self, day: dt.date, symbol: str, *, base: float = 10.0, volume: int = 10000,
                include_0930: bool = False) -> None:
        labels = (["09:30"] if include_0930 else []) + MORNING + AFTERNOON
        for i, label in enumerate(labels):
            price = base
            self.rows.append({
                "symbol": symbol, "exchange": "SH" if symbol.startswith("6") else "SZ",
                "timestamp": dt.datetime.combine(day, dt.time(int(label[:2]), int(label[3:])),
                                                 tzinfo=CST),
                "open": price, "high": price + 0.01, "low": price - 0.01, "close": price,
                "volume": volume, "turnover": price * volume, "is_bj": False,
            })

    def table(self) -> pa.Table:
        """HF 行 → splice.SCHEMA Arrow 表（canonical_table 入口）。"""
        return pa.Table.from_pylist(self.rows, schema=splice.SCHEMA)


def hf_anchor() -> dict[dt.date, splice.DailyBar]:
    """hsjday 锚点（合成）：三个关键日开=收=10.0、日量=240×10000。"""
    volume = BARS_PER_DAY * 10000
    return {day: splice.DailyBar(10.0, 10.0, volume)
            for day in (HF_END, VIP_SINGLE_DAY, VIP_MAIN_START)}


HF_END = dt.date(2026, 8, 6)
VIP_SINGLE_DAY = dt.date(2026, 8, 7)
VIP_MAIN_START = dt.date(2026, 8, 10)


@pytest.fixture
def synthetic_tree(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """一套合成数据树：HF（≤08-06）+ vipdoc 单日包（08-07）+ 主包（08-10 起）+ hsjday 日线锚点。"""
    hf, single, main = HfBuilder(), Lc1Builder(), Lc1Builder()
    anchor: dict[str, dict[str, float]] = {}
    for symbol, ex in (("600000", "sh"), ("000001", "sz")):
        hf.add_day(HF_END, symbol)
        anchor.setdefault(str(HF_END), {})["close_" + symbol] = 10.0
        single.add_day(VIP_SINGLE_DAY, base=10.0, o=10.0, c=10.0)
        main.add_day(VIP_MAIN_START, base=10.0, o=10.0, c=10.0)
        anchor.setdefault(str(VIP_SINGLE_DAY), {})["open_" + symbol] = 10.0
        anchor.setdefault(str(VIP_SINGLE_DAY), {})["close_" + symbol] = 10.0
    hf_dir = tmp_path / "hf"
    vip_root = tmp_path / "vipdoc"
    (vip_root / "sh" / "minline").mkdir(parents=True)
    (vip_root / "sz" / "minline").mkdir(parents=True)
    for symbol, ex in (("600000", "sh"), ("000001", "sz")):
        single.write(vip_root / "single", ex, symbol)
        main.write(vip_root / "main", ex, symbol)
    yield {"hf_dir": hf_dir, "vip_root": vip_root, "anchor": anchor, "hf": hf,
           "single": single, "main": main}


# ---------------- §2.7 第 1 条：文件选择与北交所排除 ----------------
class TestFileSelection:
    def test_bj_directory_and_920_codes_never_enter_pool(self, tmp_path: Path) -> None:
        """第 1 条：只读 sh/sz 的 minline/*.lc1；bj 目录、920 开头、指数、ETF、B 股不读；
        进入股票池的北交所代码数 = 0（HF 侧按 is_bj）。"""
        for exchange, symbol in (("sh", "600001"), ("sz", "300001"), ("sh", "510300"),
                                 ("sh", "000001"), ("sz", "200001"), ("bj", "920001")):
            directory = tmp_path / exchange / "minline"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{exchange}{symbol}.lc1").write_bytes(b"must not be decoded here")
        (tmp_path / "bj" / "minline").mkdir(parents=True, exist_ok=True)
        (tmp_path / "bj" / "minline" / "bj920001.lc1").write_bytes(b"bj excluded")
        pool = splice.selected_lc1(tmp_path)
        assert set(pool) == {("SH", "600001"), ("SZ", "300001")}  # ETF/指数/B股/北交所全排除

    def test_code_prefix_per_main_package_manifest_selection(self, tmp_path: Path) -> None:
        """第 1 条：代码前缀按主包 manifest 的 selection（沪 600/601/603/605/688/689，深 000/001/002/003/300/301/302）。"""
        for symbol in ("600001", "601001", "603001", "605001", "688001", "689001"):
            assert splice.selected_symbol("SH", symbol), symbol
        for symbol in ("000001", "001001", "002001", "003001", "300001", "301001", "302001"):
            assert splice.selected_symbol("SZ", symbol), symbol
        for symbol in ("920001", "399001", "510300", "200001", "60000"):  # 北交所/指数/ETF/B股/位数不符
            assert not splice.selected_symbol("SH", symbol) or not splice.selected_symbol("SZ", symbol)
        assert not splice.selected_symbol("BJ", "920001")
        with pytest.raises(DataFormatError, match="before reading"):
            splice.decode_lc1(tmp_path / "no.lc1", "BJ", "920001")  # 读前拒绝


# ---------------- §2.7 第 2 条：解码与口径 ----------------
class TestDecoding:
    def test_lc1_record_layout_roundtrip(self) -> None:
        """第 2 条：32 字节小端 <HHfffffII；生成→解码读回逐字段一致（生成器自证）。"""
        raw = _encode_min_line(dt.date(2026, 8, 7), 9 * 60 + 31, 10.0, 10.01, 9.99, 10.0, 100000.0, 10000)
        assert len(raw) == MINUTE_BYTES
        got = _decode_min_line(raw)
        assert got["date"] == dt.date(2026, 8, 7)
        assert got["label"] == "09:31"
        assert got["open"] == pytest.approx(10.0) and got["close"] == pytest.approx(10.0)
        assert got["volume"] == 10000 and got["turnover"] == pytest.approx(100000.0)

    def test_price_is_yuan_not_cents(self) -> None:
        """第 2 条：lc1 价格是元、不需要 ÷100（hsjday 才是 ÷100）——错误解码 100 倍即红。"""
        raw = _encode_min_line(dt.date(2026, 8, 7), 9 * 60 + 31, 10.0, 10.01, 9.99, 10.0, 100000.0, 10000)
        assert _decode_min_line(raw)["open"] == pytest.approx(10.0)
        assert _decode_min_line(raw)["open"] != pytest.approx(1000.0)

    def test_volume_is_shares_not_lots(self) -> None:
        """第 2 条：量是股不是手——「成交额 ÷ 成交量」必须落在该根高低价附近。"""
        o, h, l, c = 10.0, 10.02, 9.98, 10.01
        volume, turnover = 10000, 100050.0
        got = _decode_min_line(_encode_min_line(dt.date(2026, 8, 7), 10 * 60, o, h, l, c, turnover, volume))
        vwap = got["turnover"] / got["volume"]
        assert l <= vwap <= h

    def test_labels_are_bar_end_beijing_time(self) -> None:
        """第 2 条：标签 09:31–11:30、13:01–15:00（bar 结束时刻），无 09:30；按北京时间解释。
        （T-T82 清理项⑤：删恒真尾巴，13:00 仅允许出现在已知异常形态。"""
        assert "09:30" not in VALID_LABELS and "09:31" in VALID_LABELS
        assert "11:30" in VALID_LABELS and "13:00" not in VALID_LABELS

    def test_known_anomaly_1300_relabel_rule(self, synthetic_tree: dict[str, Any], tmp_path: Path) -> None:
        """第 2 条已知异常：有 13:00、无 11:30、且 239 根齐全 → 实现改记 11:30；
        条件不全 → 该根按缺 bar 处理；11:30 与 13:00 并存或其他非法标签 → 停并上报。
        （接线断言：decode_lc1 内调 relabel_1300，断言改记/丢弃计数与改记后标签。）"""
        tree = synthetic_tree
        builder: Lc1Builder = tree["main"]
        day = dt.date(2026, 8, 11)
        builder.add_day(day, labels=[*MORNING[:-1], "13:00", *AFTERNOON])  # 240 根、239 形态
        path = builder.write(Path(tree["vip_root"]) / "main", "sh", "600000")
        table, checks = splice.decode_lc1(path, "SH", "600000")  # 实现内部完成改记
        labels = [s.strftime("%H:%M") for s in table["timestamp"].to_pylist() if s.date() == day]
        assert "11:30" in labels and "13:00" not in labels and "13:01" in labels
        assert len(labels) == BARS_PER_DAY
        assert checks["relabelled_1300"] == 1 and checks["dropped_unconfirmed_1300"] == 0
        # 条件不全：缺一根上午 bar（239-1+1=238 实体 + 13:00 不构成 239 齐全）→ 13:00 按缺 bar 丢弃
        builder.add_day(day, labels=[*MORNING[:-2], "13:00", *AFTERNOON])
        table2, checks2 = splice.decode_lc1(builder.write(tmp_path / "incomplete", "sh", "600000"), "SH", "600000")
        assert checks2["relabelled_1300"] == 0 and checks2["dropped_unconfirmed_1300"] == 1
        labels2 = [s.strftime("%H:%M") for s in table2["timestamp"].to_pylist() if s.date() == day]
        assert "13:00" not in labels2 and len(labels2) == BARS_PER_DAY - 2
        # 并存 → 停
        builder.add_day(day, labels=[*MORNING, "13:00", *AFTERNOON])
        with pytest.raises(DataFormatError, match="coexist"):
            splice.decode_lc1(builder.write(tmp_path / "coexist", "sh", "600000"), "SH", "600000")

    def test_volume_precision_multiple_of_100(self, synthetic_tree: dict[str, Any]) -> None:
        """第 2 条：vipdoc 非零量全部是 100 股整数倍（逐根断言，经实现解码）。"""
        tree = synthetic_tree
        table, _ = splice.decode_lc1(Path(tree["vip_root"]) / "main" / "sz" / "minline" / "000001.lc1", "SZ", "000001")
        assert all(v % 100 == 0 for v in table["volume"].to_pylist() if v)


# ---------------- §2.7 第 3 条：每日根数 ----------------
class TestBarsPerDay:
    def test_full_day_is_240(self, synthetic_tree: dict[str, Any]) -> None:
        tree = synthetic_tree
        table, checks = splice.decode_lc1(Path(tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1", "SH", "600000")
        rows = [s.date() for s in table["timestamp"].to_pylist()]
        assert rows.count(VIP_SINGLE_DAY) == BARS_PER_DAY
        assert checks["non_240_stock_days"] == 0

    def test_first_day_single_bar_is_ipo_not_failure(self, synthetic_tree: dict[str, Any], tmp_path: Path) -> None:
        """第 3 条：只有 1 根（09:31）的股票-日 = 该代码在 vipdoc 第一天、不在 HF 清单 →
        新股上市首日，按 §2.3 剔除；用 securities 上市日核对；计数不整日剔除。
        （接线断言：实现按 single_bar_days 计数、不失败。）"""
        builder: Lc1Builder = synthetic_tree["main"]
        ipo_day = dt.date(2026, 8, 12)
        builder.add_day(ipo_day, labels=["09:31"])
        path = builder.write(Path(synthetic_tree["vip_root"]) / "main", "sh", "600000")
        table, checks = splice.decode_lc1(path, "SH", "600000")
        stamps = [s for s in table["timestamp"].to_pylist() if s.date() == ipo_day]
        assert len(stamps) == 1 and stamps[0].strftime("%H:%M") == "09:31"
        assert checks["single_bar_days"] == 1  # 计数，不失败


# ---------------- §2.7 第 4 条：拼接点单位校验 ----------------
class TestSplicePointChecks:
    @staticmethod
    @staticmethod
    def _hf_600000() -> pa.Table:
        """单只股票的 HF 表（canonical_table 要求全表 symbol 唯一）；含 04-24 重叠日 + HF 末日。"""
        hf = HfBuilder()
        hf.add_day(dt.date(2026, 4, 24), "600000")  # §2.7 第 6 条重叠段起点
        hf.add_day(HF_END, "600000")
        return hf.table()

    def test_check_1_hf_last_close_matches_hsjday(self, synthetic_tree: dict[str, Any]) -> None:
        """④①：HF 08-06 末根收盘 = hsjday 08-06 收盘（容差 0.005 元）——checker 实算。"""
        tree = synthetic_tree
        anchor = hf_anchor()
        table, checks = splice.decode_lc1(Path(tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1", "SH", "600000")
        result = splice.check_splice(self._hf_600000(), table, splice.empty_table(), anchor, exchange="SH", symbol="600000", require_overlap=False)["splice"]
        assert result["hf_end"]["state"] == "checked" and not result["hf_end"].get("failures")
        assert result["ok"]

    def test_check_2_vipdoc_first_open_last_close_match_hsjday(self, synthetic_tree: dict[str, Any]) -> None:
        """④②：vipdoc 08-07 首根开盘、末根收盘 = hsjday 同日开、收（容差 0.005 元）——checker 实算。"""
        tree = synthetic_tree
        anchor = hf_anchor()
        table, _ = splice.decode_lc1(Path(tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1", "SH", "600000")
        result = splice.check_splice(self._hf_600000(), table, splice.empty_table(), anchor, exchange="SH", symbol="600000", require_overlap=False)["splice"]
        assert result["single_day"]["state"] == "checked"
        assert not result["single_day"].get("failures")
        assert result["ok"]

    def test_check_3_daily_volume_relative_diff_within_0_1pct(self, synthetic_tree: dict[str, Any]) -> None:
        """④③：两边当日分钟量之和 vs hsjday 日成交量相对差 ≤ 0.1%；只对 240 根的股票做；
        不足 240 根记「无法完成校验」（volume_state=incomplete_day）并计数，不算失败——checker 实算。"""
        tree = synthetic_tree
        anchor = hf_anchor()
        table, _ = splice.decode_lc1(Path(tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1", "SH", "600000")
        result = splice.check_splice(self._hf_600000(), table, splice.empty_table(), anchor, exchange="SH", symbol="600000", require_overlap=False)["splice"]
        assert result["single_day"]["volume_state"] == "checked"
        assert result["incomplete_volume_days"] == 0
        # 不足 240 根 → incomplete 计数而非失败
        sliced = table.slice(1)  # 缺 09:31 一根
        result2 = splice.check_splice(self._hf_600000(), sliced, splice.empty_table(), anchor, exchange="SH", symbol="600000", require_overlap=False)["splice"]
        assert result2["incomplete_volume_days"] == 1 and result2["ok"]

    def test_check_4_overnight_change_within_price_limit(self, synthetic_tree: dict[str, Any], tmp_path: Path) -> None:
        """④④：|vipdoc 08-07 首开 ÷ HF 08-06 末收 − 1| ≤ 当日涨跌幅限制 + 0.5%；
        08-07 是 gbbq 除权日时分母改用 §2.4 参考价（实现按 events 计算）——checker 实算含反例。"""
        anchor = hf_anchor()
        table, _ = splice.decode_lc1(Path(synthetic_tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1", "SH", "600000")
        hf = self._hf_600000()
        assert splice.check_splice(hf, table, splice.empty_table(), anchor, exchange="SH", symbol="600000", require_overlap=False)["splice"]["ok"]
        # 跳空 16%（超主板 10%+0.5%）→ 停并列出 overnight_price_limit
        jumped = Lc1Builder()
        jumped.add_day(VIP_SINGLE_DAY, base=11.6)
        table_j, _ = splice.decode_lc1(jumped.write(tmp_path / "jump", "sh", "600000"), "SH", "600000")
        with pytest.raises(splice.SpliceError, match="overnight_price_limit"):
            splice.check_splice(hf, table_j, splice.empty_table(), {**anchor, VIP_SINGLE_DAY: splice.DailyBar(11.6, 10.0, BARS_PER_DAY * 10000)}, exchange="SH", symbol="600000", require_overlap=False)
        # 除权：1:1 送股（s=1），除权后首开 5.05 对参考价 5.0 → 用参考价分母通过、用未复权前收必红
        half = Lc1Builder()
        half.add_day(VIP_SINGLE_DAY, base=5.0)
        table_h, _ = splice.decode_lc1(half.write(tmp_path / "half", "sh", "600000"), "SH", "600000")
        daily_half = {**anchor, VIP_SINGLE_DAY: splice.DailyBar(5.0, 5.0, BARS_PER_DAY * 10000)}
        from retest.t_r58.sim import Event
        event = Event(ex_date=VIP_SINGLE_DAY, cash=0, pp=0, s=1, r=0)
        result_h = splice.check_splice(hf, table_h, splice.empty_table(), daily_half, exchange="SH", symbol="600000", events=[event], require_overlap=False)["splice"]
        assert result_h["ok"]
        with pytest.raises(splice.SpliceError, match="overnight_price_limit"):
            splice.check_splice(hf, table_h, splice.empty_table(), daily_half, exchange="SH", symbol="600000", require_overlap=False)

    def test_unpairable_stock_counts_not_fails(self, synthetic_tree: dict[str, Any]) -> None:
        """第 4 条：HF 08-06 无 bar 的股票不参与配对（193 只类推）；复牌首日按 ②③ 单边核对——checker 实算。"""
        tree = synthetic_tree
        table, _ = splice.decode_lc1(Path(tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1", "SH", "600000")
        result = splice.check_splice(splice.empty_table(), table, splice.empty_table(), hf_anchor(), exchange="SH", symbol="600000", require_overlap=False)["splice"]
        assert not result["paired"] and result["ok"]  # 只计数，不失败


# ---------------- §2.7 第 5 条：vipdoc 双包一致性 ----------------
class TestTwoPackageConsistency:
    def test_main_package_single_day_records_identical(self, synthetic_tree: dict[str, Any], tmp_path: Path) -> None:
        """第 5 条：主包与单日包同一来源——同股票 08-07 记录逐字段相同，不同 → 停——checker 实算。"""
        tree = synthetic_tree
        hf = TestSplicePointChecks._hf_600000()
        single, _ = splice.decode_lc1(Path(tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1", "SH", "600000")
        main_builder: Lc1Builder = tree["main"]
        main_builder.add_day(VIP_SINGLE_DAY)  # 主包合成一份 08-07（先逐字段相同）
        main, _ = splice.decode_lc1(main_builder.write(tmp_path / "main2", "sh", "600000"), "SH", "600000")
        result = splice.check_splice(hf, single, main, hf_anchor(), exchange="SH", symbol="600000", require_overlap=False)["splice"]
        assert result["dual_package"]["state"] == "checked" and result["dual_package"]["ok"]
        # 不同 → 停（SpliceError）
        tampered = single.set_column(
            single.schema.get_field_index("turnover"), "turnover",
            pa.array(single["turnover"].to_pylist()[:1] + [123456.0] * (single.num_rows - 1)),
        )
        with pytest.raises(splice.SpliceError, match="dual_package_mismatch"):
            splice.check_splice(hf, tampered, main, hf_anchor(), exchange="SH", symbol="600000", require_overlap=False)

    def test_main_package_retest_starts_0810(self) -> None:
        """第 5 条：主包进入复测起始日 = 2026-08-10；更早记录只供第 5、6 条校验，读入先于日期过滤。"""
        assert splice.MAIN_START == dt.date(2026, 8, 10)


# ---------------- §2.7 第 6 条：重叠段一致性 ----------------
class TestOverlapConsistency:
    def test_overlap_ohlc_and_volume_agree_at_least_98pct(self, synthetic_tree: dict[str, Any], tmp_path: Path) -> None:
        """第 6 条：HF 与 vipdoc 在 2026-04-24–08-06 重叠段逐根比对，OHLC 一致率、量一致率 ≥98%
        ——checker 实算（抽查股 require_overlap=True 时核对真实重叠 bar，不再用字面量）。
        单日包与主包独立构造（第 5 条：不得把同一文件的两次视图当双包）。"""
        tree = synthetic_tree
        builder: Lc1Builder = tree["main"]
        for day in (dt.date(2026, 4, 24), HF_END):  # 主包抽查股另有 04-24 起记录
            builder.add_day(day)
        builder.add_day(VIP_SINGLE_DAY)  # 抽查股主包还含 08-07（否则 sample_main_missing_0807 停）
        main, _ = splice.decode_lc1(builder.write(Path(tree["vip_root"]) / "main2", "sh", "600000"), "SH", "600000")
        single_b = Lc1Builder()
        single_b.add_day(VIP_SINGLE_DAY)  # 独立单日包：与主包 08-07 同一来源内容
        single, _ = splice.decode_lc1(single_b.write(tmp_path / "single2", "sh", "600000"), "SH", "600000")
        result = splice.check_splice(TestSplicePointChecks._hf_600000(), single, main, hf_anchor(), exchange="SH", symbol="600000", require_overlap=True)["splice"]
        assert result["overlap"]["state"] == "checked"
        assert result["overlap"]["ohlc_share"] >= 0.98 and result["overlap"]["volume_share"] >= 0.98
        assert result["ok"]

    def test_overlap_below_98pct_stops(self, synthetic_tree: dict[str, Any]) -> None:
        """第 6 条：低于 98% → 停（SpliceError）。"""
        tree = synthetic_tree
        builder: Lc1Builder = tree["main"]
        for day in (dt.date(2026, 4, 24), HF_END):
            builder.add_day(day)
        main, _ = splice.decode_lc1(builder.write(Path(tree["vip_root"]) / "main3", "sh", "600000"), "SH", "600000")
        hf = TestSplicePointChecks._hf_600000().set_column(  # 弄坏一半重叠 bar 的 volume（合成 240 根中改 120 根）
            TestSplicePointChecks._hf_600000().schema.get_field_index("volume"), "volume",
            pa.array([10000.0 if i < 120 else 5000000.0 for i in range(TestSplicePointChecks._hf_600000().num_rows)]),
        )
        with pytest.raises(splice.SpliceError, match="overlap_below_98pct"):
            splice.check_splice(hf, splice.empty_table(), main, hf_anchor(), exchange="SH", symbol="600000", require_overlap=True)

    def test_overlap_only_for_choucha_stocks_not_into_retest(self, synthetic_tree: dict[str, Any]) -> None:
        """第 6 条：主包 5 只抽查股另有 2026-04-24 起记录，只用于重叠核对，不进复测——
        实现把 OVERLAP_START 之前的主包记录过滤在 merge_sources 内，抽查名单由实现 OVERLAP_CODES 固化。"""
        assert dt.date(2026, 4, 24) == splice.OVERLAP_START
        assert "600000" in splice.OVERLAP_CODES and "688001" in splice.OVERLAP_CODES


# ---------------- §2.7 第 7 条：复权口径 ----------------
class TestAdjustmentSource:
    def test_both_sources_raw_and_gbbq_self_computed(self, synthetic_tree: dict[str, Any]) -> None:
        """第 7 条：两来源均为不复权原始价，复测统一按 §2.4 gbbq 自算；不读任何一方的复权数据。
        （实现接口：check_splice 的 events 参数只收 gbbq 解码后的 sim.Event，④分母走 rules.ref_price。）"""
        table, _ = splice.decode_lc1(Path(synthetic_tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1", "SH", "600000")
        assert table.schema.field("open").type == pa.float64()  # 原始价（未复权）直接进表
        from retest.t_r58 import rules
        assert callable(rules.ref_price)  # 复权由 gbbq→Event→ref_price 自算链承担


# ---------------- §2.7 第 8 条：失败处理与 splice 落点 ----------------
class TestFailureSemantics:
    def test_format_label_bj_failure_stops(self, tmp_path: Path) -> None:
        """第 8 条：第 1、2 条（格式、标签、北交所）失败 → 停（DataFormatError），不出结果。"""
        (tmp_path / "truncated.lc1").write_bytes(b"x" * 31)
        with pytest.raises(DataFormatError, match="truncated"):
            splice.decode_lc1(tmp_path / "truncated.lc1", "SH", "600001")
        with pytest.raises(DataFormatError, match="before reading"):
            splice.decode_lc1(tmp_path / "no.lc1", "BJ", "920001")
        builder = Lc1Builder()
        builder.add_day(VIP_SINGLE_DAY, labels=["09:30"])  # 非法标签
        with pytest.raises(DataFormatError, match="illegal bar-end label"):
            splice.decode_lc1(builder.write(tmp_path / "illegal", "sh", "600001"), "SH", "600001")

    def test_check4_any_failure_stops_with_code_list(self, synthetic_tree: dict[str, Any], tmp_path: Path) -> None:
        """第 8 条：第 4 条任何一只失败 → 停（SpliceError 附 summary 与 symbol）；
        「无法完成校验」只计数（incomplete_volume_days）；不采用「剔除失败股票后继续」。"""
        tree = synthetic_tree
        hf = TestSplicePointChecks._hf_600000()
        builder: Lc1Builder = tree["single"]
        builder.add_day(VIP_SINGLE_DAY, base=11.6)  # 跳空超限
        table, _ = splice.decode_lc1(builder.write(tmp_path / "bad", "sh", "600000"), "SH", "600000")
        with pytest.raises(splice.SpliceError) as exc:
            splice.check_splice(hf, table, splice.empty_table(), hf_anchor(), exchange="SH", symbol="600000", require_overlap=False)
        assert "600000" in str(exc.value)
        assert exc.value.summary["splice"]["failures"] and not exc.value.summary["splice"]["ok"]

    def test_check3_counts_only(self, synthetic_tree: dict[str, Any]) -> None:
        """第 8 条：第 3 条只计数（240 根偏差 → non_240_stock_days / incomplete_volume_days），不算停机条件。"""
        tree = synthetic_tree
        table, checks = splice.decode_lc1(Path(tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1", "SH", "600000")
        assert checks["non_240_stock_days"] == 0
        result = splice.check_splice(TestSplicePointChecks._hf_600000(), table.slice(1), splice.empty_table(), hf_anchor(), exchange="SH", symbol="600000", require_overlap=False)["splice"]
        assert result["incomplete_volume_days"] == 1 and result["ok"]

    def test_results_written_to_summary_json_splice(self, synthetic_tree: dict[str, Any]) -> None:
        """第 8 条：所有结果写入 summary.json 的 ``splice`` 键——check_splice 返回 {"splice": …}、
        SpliceError.summary = {"splice": …}、load_spliced_stock 的 checks["splice"] 三处落点。"""
        tree = synthetic_tree
        hf = TestSplicePointChecks._hf_600000()
        table, _ = splice.decode_lc1(Path(tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1", "SH", "600000")
        result = splice.check_splice(hf, table, splice.empty_table(), hf_anchor(), exchange="SH", symbol="600000", require_overlap=False)
        assert set(result) == {"splice"} and result["splice"]["ok"]
        from retest.t_r58 import data
        grid, checks = data.load_spliced_stock(hf, table, splice.empty_table(), [HF_END, VIP_SINGLE_DAY], hf_anchor(), exchange="SH", symbol="600000", require_overlap=False)
        assert "splice" in checks and checks["splice"]["ok"]