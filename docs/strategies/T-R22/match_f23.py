# F23 词表 v1 参考匹配器（研究侧，确定性；无网络、无麦蕊）。match(title) -> (hit: bool, categories: list)
import re, unicodedata, pathlib, yaml
LEX = yaml.safe_load((pathlib.Path(__file__).parent / "f23_lexicon_v1.yaml").read_text())
def norm(t):
    t = re.sub(r"</?[^>]+>", "", t or "")
    t = unicodedata.normalize("NFKC", t)
    for a, b in LEX["normalize"]["map"].items(): t = t.replace(a, b)
    return re.sub(r"\s+", "", t)
SPLIT = re.compile(LEX["clause_split"])
PREFIX = re.compile(LEX["title_exclude_prefix_regex"])
def _occ_hit(clause, kw, negs, after=(), resets=(), window=10):
    """关键词在子句内的每次出现：前文（含关键词本身，允许“不减持”“无保留意见”重叠）有否定词且其后没有重置词，或后文有后置否定词 → 该次出现被否定；任一次未被否定 → 命中。"""
    i = clause.find(kw)
    while i >= 0:
        pre, post = clause[:i + len(kw)], clause[i + len(kw):]
        neg_pos = max((pre.rfind(n) for n in negs if n != kw and n in pre), default=-1)
        reset_pos = max((pre.rfind(r) for r in resets if r in pre[:i]), default=-1)
        negated = (neg_pos >= 0 and neg_pos > reset_pos) or any(0 <= post.find(x) <= window for x in after)
        if not negated: return True
        i = clause.find(kw, i + 1)
    return False
def match(title):
    t = norm(title)
    if not t or PREFIX.search(t) or any(x in t for x in LEX["title_excludes"]): return False, []
    clauses = [c for c in SPLIT.split(t) if c]
    cats = []
    for name, c in LEX["categories"].items():
        negs = c.get("negations_before", []); aft = c.get("negations_after", []); rs = LEX.get("negation_resets", []); w = c.get("after_window", LEX.get("after_window", 10))
        if "require_all" in c:
            ok = any(r in t for r in c["require_any"]) and all(any(_occ_hit(cl, k, negs, aft, rs, w) for cl in clauses) for k in c["require_all"])
        else:
            ok = any(_occ_hit(cl, k, negs, aft, rs, w) for cl in clauses for k in c["keywords"])
        if ok: cats.append(name)
    return bool(cats), cats
from datetime import datetime, date, time, timedelta, timezone
CST = timezone(timedelta(hours=8), "Asia/Shanghai")   # 北京时间（A 股无夏令时，固定 +08:00）
OPEN_AM, CLOSE_AM, OPEN_PM, CLOSE_PM = time(9, 30), time(11, 30), time(13, 0), time(15, 0)
def _aware(x, name):
    if not isinstance(x, datetime) or x.tzinfo is None or x.utcoffset() is None:
        raise ValueError(f"{name} 必须是带时区的 datetime（拒绝 naive 或纯日期）：{x!r}")
    return x.astimezone(CST)
def _next_td(trading_days, d):
    for x in trading_days:
        if x > d: return x
    raise ValueError(f"交易日历未覆盖 {d} 之后")
def _normalize(x, trading_days):
    """带时区时刻 → (可交易时刻, gap)。只实现 F23 原文已写的规整：盘中 → 下一根 1 分钟 bar；盘后（含非交易日）→ 次一交易日开盘 09:30；
    盘前 → 当日 09:30（按编排者 2026-11-07 口径视为已知；原文未逐字写“盘前”，见 README 待裁定）。
    原文未覆盖的时段一律返回 (None, gap)，不自行提前可交易：午休 [11:30, 13:00)；以及下一根 bar 落在 11:30 或 15:00 的盘中边界（[11:29, 11:30)、[14:59, 15:00)）。"""
    d = x.date().isoformat(); tod = x.timetz().replace(tzinfo=None)
    if d not in trading_days or tod >= CLOSE_PM:
        return datetime.combine(date.fromisoformat(_next_td(trading_days, d)), OPEN_AM, CST), None
    if tod < OPEN_AM:
        return datetime.combine(x.date(), OPEN_AM, CST), None
    if CLOSE_AM <= tod < OPEN_PM:
        return None, "gap:lunch_break_unruled"
    nb = x.replace(second=0, microsecond=0) + timedelta(minutes=1)
    if nb.timetz().replace(tzinfo=None) in (CLOSE_AM, CLOSE_PM):
        return None, "gap:next_bar_at_session_end_unruled"
    return nb, None
def available_from_detail(t, first_seen_at, trading_days):
    """返回 (available_from, gap)。F23 可得时点 = max(t, first_seen_at) 规整后；t 为纯日期（V7 实测如此）或带时区 datetime，first_seen_at 为带时区 datetime。
    任一缺失 → (None, "gap:missing_input")；任一端落在未裁定时段 → (None, 该 gap)，待裁定，不得默认可见。只有日期 → 次一交易日 09:30。"""
    if t is None or first_seen_at is None: return None, "gap:missing_input"
    fs, g = _normalize(_aware(first_seen_at, "first_seen_at"), trading_days)
    if g: return None, g
    if isinstance(t, datetime):
        tt, g = _normalize(_aware(t, "t"), trading_days)
        if g: return None, g
    elif isinstance(t, date): tt = datetime.combine(date.fromisoformat(_next_td(trading_days, t.isoformat())), OPEN_AM, CST)
    else: raise ValueError(f"t 类型不支持：{t!r}")
    return max(tt, fs), None
def available_from(t, first_seen_at, trading_days):
    return available_from_detail(t, first_seen_at, trading_days)[0]
def window_days(trading_days, d, n=10):
    """含评估日 D 在内共 n 个交易日 [D-(n-1), D]（F23 原文：“D 及其之前共 10 个交易日内”）。trading_days 为升序 ISO 日期列表，D 必须是交易日。"""
    i = trading_days.index(d)
    return set(trading_days[max(0, i - n + 1): i + 1])
def count(rows, as_of, trading_days):
    """D 日的 f.ann_risk_count_10d（F23 ②：available_from ≤ D 09:30；“D 日 09:30 生效”）。不是盘中更新的特征：D 日内任何 as_of 都冻结在 D 09:30。
    as_of：带时区 datetime；D = as_of 的北京日期，须为交易日。as_of < D 09:30 → None（D 日值尚未生效）；否则截断时刻 cutoff = D 09:30。
    rows: [{nr, code, title, available_from}]，available_from 为带时区 datetime 或 None。本函数自行做 PIT 过滤并显式校验：naive/纯日期 → ValueError；不因日期相等默认可见。
    1) 可见 = available_from ≤ cutoff 且其北京日期 ∈ [D-9, D]；cutoff 之后（含 D 日 09:30 之后、下午新公告）的记录不参与，未来更正也不能改写过去；
    2) 存在 available_from 未知（None，含未裁定时段 gap）的记录 → 返回 None；
    3) 可见记录按 nr 或（代码、去版本后缀标题、可交易日）任一相同传递归并（并查集）；每个实体风险取 OR、至多计 1；结果与输入顺序无关。"""
    now = _aware(as_of, "as_of"); d = now.date().isoformat()
    win = window_days(trading_days, d)
    cutoff = datetime.combine(now.date(), OPEN_AM, CST)
    if now < cutoff: return None
    vis = []
    for r in rows:
        af = r.get("available_from")
        if af is None:
            return None
        af = _aware(af, "available_from")
        if af <= cutoff and af.date().isoformat() in win:
            vis.append(dict(r, _day=af.date().isoformat()))
    vs = re.compile(LEX["dedup"]["version_suffix"])
    parent = list(range(len(vis)))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    first = {}
    for i, r in enumerate(vis):
        keys = [("nr", r["nr"])] if r.get("nr") else []
        keys.append(("k2", r["code"], vs.sub("", norm(r["title"])), r["_day"]))
        for k in keys:
            if k in first: parent[find(i)] = find(first[k])
            else: first[k] = i
    risk = {}
    for i, r in enumerate(vis):
        g = find(i); risk[g] = risk.get(g, False) or match(r["title"])[0]
    return sum(risk.values())
