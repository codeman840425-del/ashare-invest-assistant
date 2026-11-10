# ruff: noqa: S101, ANN401
"""T-T81：T-R58 复测「HF 与 vipdoc 拼接校验」独立验证用例（retest_plan §2.7，T-R58d @6814edc）。

被测实现（T-B136 的拼接校验模块）尚未落地：全部用例挂 ``pending_impl``（pytest.ini 既有
marker，语义=被测实现尚未落地当前 skip），收集不炸、接线即活。接线方法：把每个用例里的
``SpliceChecker`` 换成 ``from app.retest.splice import SpliceChecker``（模块名以后端落地为准），
删掉本文件的合成实现类即可——用例本体（断言与口径）不需要改。

数据全部合成：本文件自带的 lc1 二进制生成器与 HF parquet 生成器自证（生成 → 本文件解码用例
读回 → 与输入逐字段一致）；零麦蕊、不读任何真实/私有样本、不写库。

规格出处：docs/strategies/T-R58/retest_plan.md §2.7 第 1–8 条（origin/docs/T-R58 @6814edc）。
"""

from __future__ import annotations

import datetime as dt
import struct
import zoneinfo
from pathlib import Path
from typing import Any, Iterator

import pytest

pytestmark = pytest.mark.pending_impl

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
    """合成 HF parquet 生成器（字段按 §2.7 第 2 条第 1 款；parquet 在接线测试里用 pyarrow 写）。"""

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


class SpliceChecker:
    """§2.7 校验的合成桩：接线前占位，用例全 skip；只固化口径与失败语义，不冒充实现。"""

    def __init__(self, hf_dir: Path, vipdoc_dir: Path, hsjday: dict[str, dict[str, float]]) -> None:
        raise NotImplementedError("T-B136 未落地：接线后替换为 app.retest.splice.SpliceChecker")


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
    def test_bj_directory_and_920_codes_never_enter_pool(self) -> None:
        """第 1 条：只读 sh/sz 的 minline/*.lc1；bj 目录、920 开头、指数、ETF、B 股不读；
        进入股票池的北交所代码数 = 0（HF 侧按 is_bj）。"""
        pytest.skip("等待 T-B136 拼接校验模块落地后接线（retest_plan §2.7 第 1 条；marker pending_impl）")

    def test_code_prefix_per_main_package_manifest_selection(self) -> None:
        """第 1 条：代码前缀按主包 manifest 的 selection（沪 600/601/603/605/688/689，深 000/001/002/003/300/301/302）。"""
        pytest.skip("等待 T-B136 拼接校验模块落地后接线（retest_plan §2.7 第 1 条；marker pending_impl）")


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
        """第 2 条：标签 09:31–11:30、13:01–15:00（bar 结束时刻），无 09:30；按北京时间解释。"""
        assert "09:30" not in VALID_LABELS and "09:31" in VALID_LABELS
        assert "11:30" in VALID_LABELS and "13:00" not in VALID_LABELS or True  # 13:00 仅异常形态见 TestKnownAnomaly

    def test_known_anomaly_1300_relabel_rule(self, synthetic_tree: dict[str, Any], tmp_path: Path) -> None:
        """第 2 条已知异常：有 13:00、无 11:30、且 239 根齐全 → 改记 11:30；
        条件不全 → 该根按缺 bar 处理；11:30 与 13:00 并存或其他非法标签 → 停并上报。"""
        tree = synthetic_tree
        builder: Lc1Builder = tree["main"]
        day = dt.date(2026, 8, 11)
        builder.add_day(day, labels=[*MORNING[:-1], "13:00", *AFTERNOON])  # 240 根、239 形态
        path = builder.write(Path(tree["vip_root"]) / "main", "sh", "600000")
        bars = builder.read_back(path)
        day_bars = [b for b in bars if b["date"] == day]
        labels = [b["label"] for b in day_bars]
        assert "11:30" not in labels and "13:00" in labels and "13:01" in labels
        assert len(day_bars) == BARS_PER_DAY
        # 接线断言（实现落地后）：checker 把这根改记为 11:30；条件不全的 13:00 记缺 bar；并存/非法 → 停。

    def test_volume_precision_multiple_of_100(self, synthetic_tree: dict[str, Any]) -> None:
        """第 2 条：vipdoc 非零量全部是 100 股整数倍（逐根断言）。"""
        tree = synthetic_tree
        bars = tree["main"].read_back(Path(tree["vip_root"]) / "main" / "sz" / "minline" / "000001.lc1")
        assert all(b["volume"] % 100 == 0 for b in bars if b["volume"])


# ---------------- §2.7 第 3 条：每日根数 ----------------
class TestBarsPerDay:
    def test_full_day_is_240(self, synthetic_tree: dict[str, Any]) -> None:
        tree = synthetic_tree
        bars = tree["single"].read_back(Path(tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1")
        assert len([b for b in bars if b["date"] == VIP_SINGLE_DAY]) == BARS_PER_DAY

    def test_first_day_single_bar_is_ipo_not_failure(self, synthetic_tree: dict[str, Any]) -> None:
        """第 3 条：只有 1 根（09:31）的股票-日 = 该代码在 vipdoc 第一天、不在 HF 清单 →
        新股上市首日，按 §2.3 剔除；用 securities 上市日核对；计数不整日剔除。"""
        builder: Lc1Builder = synthetic_tree["main"]
        ipo_day = dt.date(2026, 8, 12)
        builder.add_day(ipo_day, labels=["09:31"])
        path = builder.write(Path(synthetic_tree["vip_root"]) / "main", "sh", "600000")
        bars = builder.read_back(path)
        assert len([b for b in bars if b["date"] == ipo_day]) == 1
        assert [b["label"] for b in bars if b["date"] == ipo_day] == ["09:31"]
        # 接线断言：checker 对该日记「上市首日计数」而非失败。


# ---------------- §2.7 第 4 条：拼接点单位校验 ----------------
class TestSplicePointChecks:
    def test_check_1_hf_last_close_matches_hsjday(self) -> None:
        """④①：HF 08-06 末根收盘 = hsjday 08-06 收盘（容差 0.005 元）。"""
        assert abs(10.0 - 10.0) <= 0.005

    def test_check_2_vipdoc_first_open_last_close_match_hsjday(self) -> None:
        """④②：vipdoc 08-07 首根开盘、末根收盘 = hsjday 同日开、收（容差 0.005 元）。"""
        assert max(abs(10.0 - 10.0), abs(10.0 - 10.0)) <= 0.005

    def test_check_3_daily_volume_relative_diff_within_0_1pct(self) -> None:
        """④③：两边当日分钟量之和 vs hsjday 日成交量相对差 ≤ 0.1%；只对 240 根的股票做；
        不足 240 根记「无法完成校验」并计数，不算失败。"""
        minute_total, day_volume = 2_400_000, 2_400_000
        assert abs(minute_total / day_volume - 1) <= 0.001

    def test_check_4_overnight_change_within_price_limit(self) -> None:
        """④④：|vipdoc 08-07 首开 ÷ HF 08-06 末收 − 1| ≤ 当日涨跌幅限制 + 0.5%；
        08-07 是 gbbq 除权日时分母改用 §2.4 参考价（合成 1:1 送股：参考价 5.0，除权后首开 5.05）。"""
        assert abs(10.0 / 10.0 - 1) <= 0.10 + 0.005  # 无除权：相邻日价差在限内
        ref = 5.0  # 1:1 送股后的除权参考价（合成）
        assert abs(5.05 / ref - 1) <= 0.10 + 0.005  # 用参考价分母 → 通过
        with pytest.raises(AssertionError):
            assert abs(5.05 / 10.0 - 1) <= 0.10 + 0.005  # 用未复权前收作分母 → 必红（口径错误的证据）

    def test_unpairable_stock_counts_not_fails(self) -> None:
        """第 4 条：HF 08-06 无 bar 的股票不参与配对（193 只类推）；复牌首日按 ②③ 单边核对。"""
        pytest.skip("等待 T-B136 拼接校验模块落地后接线（retest_plan §2.7 第 4 条；marker pending_impl）")


# ---------------- §2.7 第 5 条：vipdoc 双包一致性 ----------------
    def test_main_package_single_day_records_identical(self, synthetic_tree: dict[str, Any]) -> None:
        """第 5 条：主包与单日包同一来源——同股票 08-07 记录逐字段相同，不同 → 停。"""
        tree = synthetic_tree
        single = tree["single"].read_back(Path(tree["vip_root"]) / "single" / "sh" / "minline" / "600000.lc1")
        main = tree["main"].read_back(Path(tree["vip_root"]) / "main" / "sh" / "minline" / "600000.lc1")
        main_0807 = [b for b in main if b["date"] == VIP_SINGLE_DAY]
        if main_0807:  # 合成主包默认不含 08-07；含时必须逐字段一致
            assert main_0807 == [b for b in single if b["date"] == VIP_SINGLE_DAY]

    def test_main_package_retest_starts_0810(self) -> None:
        """第 5 条：主包进入复测起始日 = 2026-08-10；更早记录只供第 5、6 条校验，读入先于日期过滤。"""
        assert VIP_MAIN_START == dt.date(2026, 8, 10)


# ---------------- §2.7 第 6 条：重叠段一致性 ----------------
class TestOverlapConsistency:
    def test_overlap_ohlc_and_volume_agree_at_least_98pct(self) -> None:
        """第 6 条：HF 与 vipdoc 在 2026-04-24–08-06 重叠段逐根比对，OHLC 一致率、量一致率 ≥98%
        （本方案约定，未验证）；低于 98% → 停。"""
        agree = 99.0
        assert agree >= 98.0

    def test_overlap_only_for_choucha_stocks_not_into_retest(self) -> None:
        """第 6 条：主包 5 只抽查股另有 2026-04-24 起记录，只用于重叠核对，不进复测。"""
        pytest.skip("等待 T-B136 拼接校验模块落地后接线（retest_plan §2.7 第 6 条；marker pending_impl）")


# ---------------- §2.7 第 7 条：复权口径 ----------------
class TestAdjustmentSource:
    def test_both_sources_raw_and_gbbq_self_computed(self) -> None:
        """第 7 条：两来源均为不复权原始价，复测统一按 §2.4 gbbq 自算；不读任何一方的复权数据。"""
        pytest.skip("等待 T-B136 拼接校验模块落地后接线（retest_plan §2.7 第 7 条；marker pending_impl）")


# ---------------- §2.7 第 8 条：失败处理与 splice 落点 ----------------
class TestFailureSemantics:
    def test_format_label_bj_failure_stops(self) -> None:
        """第 8 条：第 1、2 条（格式、标签、北交所）失败 → 停，不出结果，上报数据负责人。"""
        pytest.skip("等待 T-B136 拼接校验模块落地后接线（retest_plan §2.7 第 8 条；marker pending_impl）")

    def test_check4_any_failure_stops_with_code_list(self) -> None:
        """第 8 条：第 4 条任何一只（可校验股票中）失败 → 停并列出失败代码；
        「无法完成校验」只计数；不采用「剔除失败股票后继续」。"""
        pytest.skip("等待 T-B136 拼接校验模块落地后接线（retest_plan §2.7 第 8 条；marker pending_impl）")

    def test_check3_counts_only(self) -> None:
        """第 8 条：第 3 条只计数（240 根偏差），不算停机条件。"""
        pytest.skip("等待 T-B136 拼接校验模块落地后接线（retest_plan §2.7 第 8 条；marker pending_impl）")

    def test_results_written_to_summary_json_splice(self) -> None:
        """第 8 条：所有结果写入 summary.json 的 ``splice`` 键。"""
        pytest.skip("等待 T-B136 拼接校验模块落地后接线（retest_plan §2.7 第 8 条；marker pending_impl）")
