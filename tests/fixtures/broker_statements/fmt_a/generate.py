#!/usr/bin/env python3
# SYNTHETIC
# -----------------------------------------------------------------------------
# 券商 fmt_a（成交明细 / 资金持仓）异常与边界夹具生成脚本
#
# - 仅依赖 Python 标准库。
# - 输入：同目录下已脱敏的主夹具 trades_sample.txt、positions_sample.txt
#   （本脚本不生成、也不修改这两个主夹具）。
# - 输出：19 个异常/边界夹具 + meta.json。
# - 脚本内出现的代码、名称、编号、金额全部是虚构值，或取自已脱敏主夹具；
#   不含任何真实账户数据。
#
# 用法：
#   python3 generate.py            # 在本目录（重新）生成夹具与 meta.json
#   python3 generate.py --check    # 只比对，不写文件；有差异则退出码 1
#   python3 generate.py --out DIR  # 输出到其他目录
# -----------------------------------------------------------------------------
import argparse
import hashlib
import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
CRLF = b"\r\n"
ROW_LEN = 365           # 构造数据行的统一字节长度（与主夹具多数行一致）
POS_ROW_LEN = 181
D = Decimal

# 虚构费率，仅用于让构造行内部自洽（发生金额 = ±成交金额 − 费用）
RATE_COMMISSION = D("0.0001")
RATE_STAMP_SELL = D("0.0005")
RATE_TRANSFER = D("0.00001")
RATE_OTHER = D("0.0000541")

# 虚构账户标识（与主夹具一致的虚构值）
SH_HOLDER, SH_SEAT = "A000000001", "90001"
SZ_HOLDER, SZ_SEAT = "0000000001", "900002"


def q2(x):
    return D(x).quantize(D("0.01"), rounding=ROUND_HALF_UP)


# ----------------------------------------------------------------- 读取主夹具
def read_lines(name):
    with open(os.path.join(HERE, name), "rb") as fh:
        data = fh.read()
    assert data.endswith(CRLF), name
    return data[:-2].split(CRLF)


T = read_lines("trades_sample.txt")
SEP, BLANK, HDR, ROWS, TAIL = T[0], T[1], T[2], T[3:-1], T[-1]
assert BLANK == b"" and TAIL == b" " and len(ROWS) == 66

P = read_lines("positions_sample.txt")
P_SUMMARY, P_SEP, P_BLANK, P_HDR, P_ROWS = P[0], P[1], P[2], P[3], P[4:]


def col_starts(header):
    s, prev = [], b" "
    for i, ch in enumerate(header):
        c = header[i:i + 1]
        if c != b" " and prev == b" ":
            s.append(i)
        prev = c
    return s


ST = col_starts(HDR)
PST = col_starts(P_HDR)
assert len(ST) == 20 and len(PST) == 11


def split_fixed(line, starts, enc="gbk"):
    out = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(line)
        out.append(line[s:e].decode(enc).strip())
    return out


def build_fixed(fields, starts, total, enc="gbk"):
    """按字节定宽拼一行：每列左对齐，右侧补空格到下一列起点，末列补到 total。"""
    buf = b""
    for i, f in enumerate(fields):
        b = f.encode(enc)
        end = starts[i + 1] if i + 1 < len(starts) else total
        width = end - starts[i]
        assert len(b) <= width, (f, width)
        buf += b + b" " * (width - len(b))
    return buf


def row_fields(n):           # n = 主夹具中的数据行序号（1 起）
    return split_fixed(ROWS[n - 1], ST)


NAME = {}
for r in ROWS:
    f = split_fixed(r, ST)
    NAME[f[2]] = f[3]


def holder_seat(code):
    return (SH_HOLDER, SH_SEAT) if code.startswith("6") else (SZ_HOLDER, SZ_SEAT)


def file_bytes(lines, eol=CRLF, final_eol=True):
    return eol.join(lines) + (eol if final_eol else b"")


def std(rows):               # 分隔线 + 空行 + 表头 + 数据 + 单空格行 + CRLF
    return file_bytes([SEP, BLANK, HDR] + rows + [TAIL])


# ------------------------------------------------------------ 构造成交行
class Chain:
    """资金余额链：剩余金额 = 上一笔剩余金额 + 发生金额。"""

    def __init__(self, start):
        self.bal = D(start)

    def row(self, date, time, code, side, qty, price, order_no, trade_no,
            remark, amount=None, fee_base=None, net_adjust="0", net=None,
            zero_fees=False):
        qty, price = D(qty), D(price)
        if amount is None:
            amount = q2(abs(qty) * price) if qty != 0 else D("0")
        amount = D(amount)
        base = amount if fee_base is None else D(fee_base)
        is_sell = side == "卖出"
        if zero_fees or base == 0:
            fees = [D("0")] * 4
        else:
            fees = [q2(base * RATE_COMMISSION),
                    q2(base * RATE_STAMP_SELL) if is_sell else D("0"),
                    q2(base * RATE_TRANSFER),
                    q2(base * RATE_OTHER)]
        if net is None:
            net = (base if is_sell else -base) - sum(fees) + D(net_adjust)
            if base == 0:
                net = D("0")
        net = q2(net)
        self.bal += net
        holder, seat = holder_seat(code)
        return [date, time, code, NAME[code], side,
                "%.2f" % qty if isinstance(qty, D) else qty,
                "%.8f" % price, "%.2f" % amount, order_no, trade_no,
                "%.2f" % net, "%.2f" % self.bal, order_no, holder, seat,
                "%.2f" % fees[0], "%.2f" % fees[1], "%.2f" % fees[2],
                "%.2f" % fees[3], remark]


def mk(fields):
    return build_fixed(fields, ST, ROW_LEN)


def trade_no(prefix, k):
    return "-%d" % (prefix + 7 * k)


# ------------------------------------------------------------ 各夹具
def gen():
    out = {}

    # 编码 / 换行
    first5 = ROWS[:5]
    out["trades_lf.txt"] = file_bytes([SEP, BLANK, HDR] + first5 + [TAIL], eol=b"\n")
    utf8 = std(first5).decode("gbk").encode("utf-8")
    out["trades_utf8.txt"] = utf8
    out["trades_utf8_bom.txt"] = b"\xef\xbb\xbf" + utf8

    # 空行 / 纯空格 / Tab
    out["trades_blank_lines.txt"] = file_bytes(
        [SEP, BLANK, HDR, ROWS[0], b"", ROWS[1], b"      ", ROWS[2], b"\t", b"",
         ROWS[3], b"", TAIL])

    # 截断
    out["trades_truncated_last_line.txt"] = file_bytes(
        [SEP, BLANK, HDR] + ROWS[:3] + [ROWS[3][:160]], final_eol=False)
    out["trades_truncated_mid_char.txt"] = file_bytes(
        [SEP, BLANK, HDR, ROWS[0], ROWS[1][:51]], final_eol=False)

    # 多列：在“成交金额”之后（委托编号起点）插入 16 字节宽的未知列
    ins = ST[8]
    extra_vals = ["0", "1", "0"]
    hdr_x = HDR[:ins] + "扩展标志".encode("gbk").ljust(16) + HDR[ins:]
    rows_x = [r[:ins] + v.encode().ljust(16) + r[ins:] for r, v in zip(ROWS[:3], extra_vals)]
    out["trades_extra_column.txt"] = file_bytes([SEP, BLANK, hdr_x] + rows_x + [TAIL])

    # 缺列：去掉“成交价格”整列
    a, b = ST[6], ST[7]
    out["trades_missing_column.txt"] = file_bytes(
        [SEP, BLANK, HDR[:a] + HDR[b:]] + [r[:a] + r[b:] for r in ROWS[:3]] + [TAIL])

    # 列错位
    r2 = row_fields(2)
    r2[3] = r2[3][:2] + " " + r2[3][2:]               # 名称内部插入单个空格
    r3 = ROWS[2]
    q0 = ST[5]
    r3 = r3[:q0 - 2] + r3[q0:ST[6]] + b"  " + r3[ST[6]:]  # 成交数量左移 2 字节
    r4 = row_fields(4)
    r4[14] = ""                                        # 席位代码为空
    out["trades_column_mismatch.txt"] = std([ROWS[0], mk(r2), r3, mk(r4)])

    # 同文件重复
    d8 = row_fields(3)
    d8[0], d8[1] = "20261012", "93001"
    out["trades_duplicates_in_file.txt"] = std(ROWS[:3] + [ROWS[1], mk(d8)])

    # GB18030 四字节字符
    g = row_fields(1)
    g[3] = g[3][:2] + "\u4dae" + g[3][3:]
    out["trades_gb18030_ext_char.txt"] = std(
        [build_fixed(g, ST, ROW_LEN, enc="gb18030"), ROWS[1]])

    # 只有表头 / 空文件
    out["trades_header_only.txt"] = std([])
    out["empty.txt"] = b""

    # 方向符号与数值错误
    c = Chain("1000000.00")
    day = "20261030"
    tn = lambda k: trade_no(8100000001, k)
    rows = [
        c.row(day, "93101", "300001", "卖出", "-1000", "100", "9001", tn(0), "证券卖出"),
        c.row(day, "93102", "300001", "买入", "-1000", "100", "9002", tn(1), "证券买入"),
        c.row(day, "93103", "300001", "卖出", "1000", "100", "9003", tn(2), "证券卖出"),
        c.row(day, "93104", "600001", "买入", "1000", "-29.4", "9004", tn(3), "证券买入",
              amount="-29400.00"),
        c.row(day, "93105", "600001", "买入", "1000", "29.4", "9005", tn(4), "证券买入",
              amount="29500.00", fee_base="29400.00"),
        c.row(day, "93106", "600001", "买入", "0", "29.4", "9006", tn(5), "证券买入"),
        c.row(day, "93107", "600001", "买入", "1000", "29.4", "9007", tn(6), "证券买入",
              net_adjust="1.00"),
    ]
    out["trades_sign_and_value_errors.txt"] = std([mk(r) for r in rows])

    # 撤单 / 废单
    c = Chain("1000000.00")
    rows = [
        c.row(day, "93201", "600001", "买入", "1000", "29.4", "9101", trade_no(8100000101, 0), "证券买入"),
        c.row(day, "93202", "600001", "买入", "0", "0", "9102", "0", "买入撤单"),
        c.row(day, "93203", "300001", "撤单", "1000", "0", "9103", "0", "撤单", amount="0"),
        c.row(day, "93204", "300001", "买入", "0", "0", "9104", "0", "废单"),
        c.row(day, "93205", "600001", "卖出", "-500", "30", "9105", trade_no(8100000101, 1), "证券卖出"),
    ]
    out["trades_cancelled.txt"] = std([mk(r) for r in rows])

    # 非成交业务
    c = Chain("1000000.00")
    rows = [
        c.row(day, "0", "002001", "红利入账", "0", "0", "0", "0", "红利入账", net="1234.50"),
        c.row(day, "0", "002001", "股息红利税补缴", "0", "0", "0", "0", "股息红利税补缴", net="-123.45"),
        c.row(day, "0", "301002", "新股入帐", "500", "0", "0", "0", "新股入帐", amount="0"),
        c.row(day, "0", "600001", "其他业务", "0", "0", "0", "0", "未知业务类型"),
    ]
    out["trades_non_trade_events.txt"] = std([mk(r) for r in rows])

    # 格式错误
    c = Chain("1000000.00")
    tn = lambda k: trade_no(8300000001, k)
    rows = [
        c.row("20261332", "100001", "600001", "买入", "1000", "29.4", "9201", tn(0), "证券买入"),
        c.row(day, "256000", "600001", "买入", "1000", "29.4", "9202", tn(1), "证券买入"),
        c.row(day, "9305", "600001", "买入", "1000", "29.4", "9203", tn(2), "证券买入"),
        c.row(day, "93005", "600001", "买入", "1000", "29.4", "9204", tn(3), "证券买入"),
        c.row(day, "93006", "600001", "买入", "1000", "29.4", "9205", tn(4), "证券买入"),
    ]
    rows[3][5] = "1,000.00"
    rows[4][5] = "１０００.００"
    out["trades_bad_formats.txt"] = std([mk(r) for r in rows])

    # 重导重叠：主夹具末 3 笔 + 2 笔新成交（资金链接续主夹具末笔余额）
    c = Chain(split_fixed(ROWS[-1], ST)[11])
    rows = [
        c.row(day, "93501", "301002", "买入", "1000", "33", "9001", trade_no(8200000001, 0), "证券买入"),
        c.row(day, "100102", "301002", "卖出", "-1000", "33.5", "9002", trade_no(8200000001, 1), "证券卖出"),
    ]
    out["trades_reimport_overlap.txt"] = std(ROWS[-3:] + [mk(r) for r in rows])

    # 多币种持仓：主夹具持仓 + 1 条虚构持仓 + 美元摘要行
    new_pos = ["2", "688001", NAME["688001"], "3000.00", "3000.00", "55.0000", "56.2300",
               "168690.00", "3690.00", "2.236", SH_HOLDER]
    kv = {}
    for tok in P_SUMMARY.decode("gbk").split():
        if ":" in tok and not tok.endswith(":"):
            k, v = tok.split(":", 1)
            kv[k] = D(v)
    kv["参考市值"] += D(new_pos[7])
    kv["资产"] += D(new_pos[7])
    kv["盈亏"] += D(new_pos[8])
    order = ["余额", "可用", "可取", "参考市值", "资产", "盈亏"]
    cny = "人民币: " + "  ".join("%s:%s" % (k, kv[k]) for k in order) + " "
    usd = "美元: 余额:1000.00  可用:1000.00  可取:1000.00  参考市值:0.00  资产:1000.00  盈亏:0.00 "
    out["positions_multi_currency.txt"] = file_bytes(
        [cny.encode("gbk"), usd.encode("gbk"), P_SEP, P_BLANK, P_HDR] + P_ROWS
        + [build_fixed(new_pos, PST, POS_ROW_LEN)])
    return out


# ------------------------------------------------------------ meta.json
FILE_INFO = {
    "trades_sample.txt": ("trades", "gbk", "CRLF", "脱敏后的成交明细（66 笔，与原导出逐行逐字节等长）；非本脚本生成"),
    "positions_sample.txt": ("positions", "gbk", "CRLF", "脱敏后的资金持仓快照（与原导出逐行逐字节等长）；非本脚本生成"),
    "trades_lf.txt": ("trades", "gbk", "LF", "换行为 LF 的成交明细（主夹具前 5 笔）"),
    "trades_utf8.txt": ("trades", "utf-8", "CRLF", "UTF-8 无 BOM，按显示宽度对齐（主夹具前 5 笔）"),
    "trades_utf8_bom.txt": ("trades", "utf-8-sig", "CRLF", "UTF-8 带 BOM（主夹具前 5 笔）"),
    "trades_blank_lines.txt": ("trades", "gbk", "CRLF", "数据行之间夹空行、纯空格行、纯 Tab 行（主夹具前 4 笔）"),
    "trades_truncated_last_line.txt": ("trades", "gbk", "CRLF（末行无换行）", "末行在成交编号中途截断"),
    "trades_truncated_mid_char.txt": ("trades", "gbk", "CRLF（末行无换行）", "末行在双字节汉字中间截断"),
    "trades_extra_column.txt": ("trades", "gbk", "CRLF", "多一个未知列“扩展标志”"),
    "trades_missing_column.txt": ("trades", "gbk", "CRLF", "缺少必填列“成交价格”"),
    "trades_column_mismatch.txt": ("trades", "gbk", "CRLF", "列错位、席位代码为空、名称含单个空格"),
    "trades_duplicates_in_file.txt": ("trades", "gbk", "CRLF", "同文件重复行；同成交编号不同日期"),
    "trades_gb18030_ext_char.txt": ("trades", "gb18030", "CRLF", "证券名称含 GB18030 四字节字符"),
    "trades_header_only.txt": ("trades", "gbk", "CRLF", "只有分隔线与表头"),
    "empty.txt": ("unknown", None, None, "0 字节空文件"),
    "trades_sign_and_value_errors.txt": ("trades", "gbk", "CRLF", "数量符号与方向不符、负价格、金额不符、零数量、发生金额不符"),
    "trades_cancelled.txt": ("trades", "gbk", "CRLF", "撤单/废单行与正常成交混排"),
    "trades_non_trade_events.txt": ("trades", "gbk", "CRLF", "红利入账、股息红利税补缴、新股入帐、未知业务"),
    "trades_bad_formats.txt": ("trades", "gbk", "CRLF", "非法日期/时间、千分位、全角数字、5 位时间"),
    "trades_reimport_overlap.txt": ("trades", "gbk", "CRLF", "与主夹具末 3 笔重叠 + 2 笔新成交"),
    "positions_multi_currency.txt": ("positions", "gbk", "CRLF", "两条持仓 + 美元摘要行"),
}


def data_rows(name, data):
    if not data:
        return 0
    if name.startswith("positions"):
        lines = data.replace(b"\r\n", b"\n").split(b"\n")
        return sum(1 for l in lines if l[:1].isdigit())
    lines = data.replace(b"\r\n", b"\n").split(b"\n")
    return sum(1 for l in lines if l.lstrip(b"\xef\xbb\xbf")[:2] == b"20")


def build_meta(files):
    entries = []
    for name in sorted(FILE_INFO):
        data = files[name]
        kind, enc, eol, desc = FILE_INFO[name]
        entries.append({
            "file": name,
            "kind": kind,
            "parser_hint": {"trades": "fmt_a_trades_v1", "positions": "fmt_a_positions_v1"}.get(kind),
            "encoding": enc,
            "line_ending": eol,
            "bytes": len(data),
            "physical_lines": data.count(b"\n") + (0 if (not data or data.endswith(b"\n")) else 1),
            "data_lines": data_rows(name, data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "synthetic": True,
            "origin": "desensitized_main" if name in ("trades_sample.txt", "positions_sample.txt") else "generate.py",
            "description": desc,
        })
    meta = {
        "marker": "# SYNTHETIC",
        "synthetic": True,
        "format": "fmt_a",
        "generator": "generate.py",
        "note": "全部为虚构/脱敏数据；主夹具为人工脱敏结果，其余由 generate.py 自主夹具派生。期望解析结果见 README.md。",
        "files": entries,
    }
    return (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default=HERE)
    args = ap.parse_args()
    gen_files = gen()
    all_files = dict(gen_files)
    for n in ("trades_sample.txt", "positions_sample.txt"):
        with open(os.path.join(HERE, n), "rb") as fh:
            all_files[n] = fh.read()
    gen_files["meta.json"] = build_meta(all_files)
    bad = 0
    for name, data in sorted(gen_files.items()):
        path = os.path.join(args.out, name)
        if args.check:
            try:
                with open(path, "rb") as fh:
                    same = fh.read() == data
            except FileNotFoundError:
                same = False
            print(("OK   " if same else "DIFF ") + name)
            bad += not same
        else:
            os.makedirs(args.out, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
            print("wrote " + name)
    if args.check:
        print("%d file(s) differ" % bad)
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
