# T-R22 F23 词表 v1 离线检查（研究侧；无网络、无麦蕊）。用法：python check_f23.py → PASS/FAIL
import pathlib, sys, collections, yaml
D = pathlib.Path(__file__).parent; sys.path.insert(0, str(D))
class U(yaml.SafeLoader): pass
def _m(l, n, deep=False):
    ks = [l.construct_object(k, deep=deep) for k, _ in n.value]; assert len(ks) == len(set(ks)), f"重复键 {ks}"
    return yaml.SafeLoader.construct_mapping(l, n, deep)
U.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _m)
for f in ("f23_lexicon_v1.yaml", "f23_offline_cases.yaml", "known_risk_announcements.yaml"): yaml.load((D / f).read_text(), Loader=U)
from match_f23 import match, count, LEX
err = []
# 1 正反例：期望值为人工写定
cases = yaml.safe_load((D / "f23_offline_cases.yaml").read_text())["cases"]
for c in cases:
    if match(c["title"])[0] != c["expect"]: err.append(f"case {c['keyword']} {c['title']}")
tally = collections.defaultdict(lambda: [0, 0])
for c in cases: tally[c["keyword"]][0 if c["expect"] else 1] += 1
kws = [k for c in LEX["categories"].values() for k in c.get("keywords", [])] + ["减持(控股股东/实控人)"]
for k in kws:
    if tally[k][0] < 2 or tally[k][1] < 1: err.append(f"覆盖不足 {k} {tally[k]}")
# 2 已知风险公告：全部命中
known = yaml.safe_load((D / "known_risk_announcements.yaml").read_text())["announcements"]
if len(known) < 10: err.append("已知风险公告 < 10")
if any(a["security_code"] == "301030" for a in known): err.append("301030 有争议，不得计入验收清单")
for a in known:
    if not match(a["title"])[0]: err.append("漏 " + a["title"])
    if not (isinstance(a["security_code"], str) and len(a["security_code"]) == 6 and a["security_code"].isdigit()): err.append("代码须为 6 位字符串 " + str(a["security_code"]))
    if len(a["body_quote"]) > 80: err.append("短引超过 80 字 " + a["security_code"])
# 3 窗口、PIT、归并、聚合（虚构；预期值独立写定）
import itertools
from datetime import datetime, date, timedelta
from match_f23 import window_days, available_from, CST
TD = ["2026-10-20","2026-10-21","2026-10-22","2026-10-23","2026-10-26","2026-10-27","2026-10-28","2026-10-29","2026-10-30","2026-11-02","2026-11-03","2026-11-04"]
def at(day, hm="09:30"): return datetime.fromisoformat(f"{day}T{hm}:00").replace(tzinfo=CST)
AS_OF = at("2026-11-03", "15:30")      # D=2026-11-03 盘后求值
if window_days(TD, "2026-11-03") != set(TD[1:11]): err.append("窗口应为含 D 共 10 个交易日 [2026-10-21, 2026-11-03]")
R = "【虚构】关于收到中国证监会《立案告知书》的公告"; N = "【虚构】关于召开股东会的通知"
def rec(nr, title, af, code="000001"): return dict(nr=nr, code=code, title=title, available_from=af)
T = {  # 名称: (rows, as_of, 期望)
 "边界含D与D-9": ([rec("a", R, at("2026-11-03")), rec("b", "【虚构】关于董事被留置的公告", at("2026-10-21"))], AS_OF, 2),
 "D-10在窗外": ([rec("a", R, at("2026-10-20"))], AS_OF, 0),
 "未来记录不进入": ([rec("a", R, at("2026-11-04"))], AS_OF, 0),
 "未来更正不改写过去": ([rec("a", N, at("2026-11-02")), rec("a", R, at("2026-11-04"))], AS_OF, 0),
 "同nr先负后正": ([rec("a", N, at("2026-11-02")), rec("a", R, at("2026-11-02", "10:00"))], AS_OF, 1),
 "版本更正归并": ([rec("a", R, at("2026-11-02")), rec("b", R + "（更正后）", at("2026-11-02", "13:05"))], AS_OF, 1),
 "跨链接同主键": ([rec("a", R, at("2026-11-02")), rec("b", R, at("2026-11-02", "14:00"))], AS_OF, 1),
 "传递归并": ([rec("a", R, at("2026-11-02")), rec("a", N, at("2026-11-02")), rec("b", N, at("2026-11-02"))], AS_OF, 1),
 "多类别只计1": ([rec("a", "【虚构】关于公司股票被实施其他风险警示及可能被实施退市风险警示的公告", at("2026-11-02"))], AS_OF, 1),
 "不同证券分开": ([rec("a", R, at("2026-11-02")), rec("b", R, at("2026-11-02"), "000002")], AS_OF, 2),
 "同标题不同日分开": ([rec("a", R, at("2026-11-02")), rec("b", R, at("2026-11-03"))], AS_OF, 2),
 "空且新鲜为0": ([], AS_OF, 0),
 "D日09:30之前可见": ([rec("a", R, at("2026-11-03", "09:29"))], at("2026-11-03", "09:30"), 1),
 "恰等D日09:30可见": ([rec("a", R, at("2026-11-03", "09:30"))], at("2026-11-03", "09:30"), 1),
 "D日09:30之后不可见": ([rec("a", R, at("2026-11-03", "09:31"))], at("2026-11-03", "09:30"), 0),
 "14点评估不带入10点公告": ([rec("a", R, at("2026-11-03", "10:00"))], at("2026-11-03", "14:00"), 0),
 "14点评估等于09:30冻结值": ([rec("a", R, at("2026-11-03", "09:30")), rec("b", "【虚构】关于董事被留置的公告", at("2026-11-03", "10:00"))], at("2026-11-03", "14:00"), 1),
 "D日之后的更正不覆盖": ([rec("a", N, at("2026-11-03", "09:30")), rec("a", R, at("2026-11-03", "10:01"))], at("2026-11-03", "14:00"), 0),
 "as_of早于D日09:30→null": ([rec("a", R, at("2026-11-02"))], at("2026-11-03", "09:29"), None),
 "未知可得时点→null": ([rec("a", R, at("2026-11-02")), rec("b", N, None)], AS_OF, None),
}
for name, (rows, asof, exp) in T.items():
    for perm in itertools.permutations(rows):
        got = count(list(perm), asof, TD)
        if got != exp: err.append(f"{name}: 顺序 {[r['nr'] for r in perm]} 得 {got} 期望 {exp}"); break
# 显式拒绝：naive / 纯日期，不因日期相等默认可见
for bad_asof, bad_rows in ((datetime(2026, 11, 3, 15, 30), []), (date(2026, 11, 3), []), (AS_OF, [rec("a", R, date(2026, 11, 3))]), (AS_OF, [rec("a", R, datetime(2026, 11, 3, 9, 30))])):
    try: count(bad_rows, bad_asof, TD); err.append(f"应拒绝 {bad_asof!r} {bad_rows}")
    except ValueError: pass
# available_from 规整（F23：max(t, first_seen_at)；只有日期 → 次一交易日 09:30；盘中 → 下一根 1 分钟）
AF = [((date(2026, 11, 2), at("2026-11-02", "08:00")), at("2026-11-03", "09:30")),        # 只有日期 → 次一交易日开盘
      ((date(2026, 11, 2), at("2026-11-03", "10:15")), at("2026-11-03", "10:16")),        # 首次观测更晚，盘中 → 下一 bar
      ((at("2026-11-03", "10:15").replace(second=20), at("2026-11-03", "10:15")), at("2026-11-03", "10:16")),
      ((at("2026-11-03", "15:20"), at("2026-11-03", "15:20")), at("2026-11-04", "09:30")),  # 盘后
      ((at("2026-11-03", "08:10"), at("2026-11-03", "08:10")), at("2026-11-03", "09:30")),  # 盘前
      ((at("2026-11-03", "12:00"), at("2026-11-03", "12:00")), None),                       # 午休：未裁定 gap
      ((at("2026-11-03", "11:30"), at("2026-11-03", "11:30")), None),
      ((at("2026-11-03", "11:29").replace(second=10), at("2026-11-03", "11:29")), None),    # 下一 bar=11:30
      ((at("2026-11-03", "14:59"), at("2026-11-03", "14:59")), None),                       # 下一 bar=15:00
      ((date(2026, 11, 2), None), None), ((None, at("2026-11-03")), None)]
from match_f23 import available_from_detail
if available_from_detail(at("2026-11-03", "12:00"), at("2026-11-03", "12:00"), TD)[1] != "gap:lunch_break_unruled": err.append("午休应标 gap")
for (t, fs), exp in AF:
    if available_from(t, fs, TD) != exp: err.append(f"available_from({t}, {fs}) = {available_from(t, fs, TD)} 期望 {exp}")
print(f"cases {len(cases)} keywords {len(kws)} known {len(known)} count_tests {len(T)} af_tests {len(AF)}")
print("PASS" if not err else "FAIL\n" + "\n".join(err)); sys.exit(1 if err else 0)
