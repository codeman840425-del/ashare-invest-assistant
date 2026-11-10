# F23 词表 v3 参考匹配器（T-R62；T-A152 定向修订，研究侧，确定性；无网络、无麦蕊）。由 match_f23_v2.py 复制，增加 policy_rules（询价转让一律命中且优先于整条排除；控制人/一致行动协议到期或解除 + 权益变动保守命中）。
# T-R63 返修（RV-20 两个 P1）：① exclude_all_of 作用域收敛到「他方主体」子句（不跨子句吞整类、自身事项不排除）；② 渠道型否定（不通过/未通过/不会通过）只否掉被否渠道，另有真实渠道即命中。词表本体未改。
# T-R63b 第二轮（RV-20b）：① 排除只抹「他方事件」跨度、不删整个子句（自身风险词保留），自身称谓补「发行人/本公司及关联主体/及其子公司」复合形态，中间态一律不排除；② 渠道否定改为「从否定短语起整段标否定」（嵌套渠道词幂等、回看到子句边界不按字数）。
# 原注释：由 T-R22/match_f23.py（v1）复制，只改词表文件名并增加 controller_equity 类型与 flags。
# match(title) -> (hit: bool, categories: list)；match_detail(title) -> (hit, categories, flags)
import re, unicodedata, pathlib, yaml
LEX = yaml.safe_load((pathlib.Path(__file__).parent / "f23_lexicon_v3.yaml").read_text(encoding="utf-8"))
def norm(t):
    t = re.sub(r"</?[^>]+>", "", t or "")
    t = unicodedata.normalize("NFKC", t)
    for a, b in LEX["normalize"]["map"].items(): t = t.replace(a, b)
    return re.sub(r"\s+", "", t)
SPLIT = re.compile(LEX["clause_split"])
PREFIX = re.compile(LEX["title_exclude_prefix_regex"])
# —— T-R63 返修常量（词表未改；作用域与主体判定在匹配器内）——
# T-R63b：自身称谓补复合形态（发行人及其子公司等），中间态一律不排除。
SELF_MARKERS = ("本公司", "我公司", "公司自身", "公司本身", "发行人",
                "本公司及其", "本公司及", "公司及子公司", "及其子公司", "及其控股子公司")
OTHER_MARKERS = ("他方", "对方", "第三方", "其他公司", "他公司", "另一公司", "某公司", "对外", "外部")
COMPANY_NAME = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9]{1,}(?:股份有限公司|有限责任公司|有限公司|公司)")
CHANNELS = ("集中竞价交易", "集中竞价", "二级市场", "大宗交易", "协议转让", "询价转让", "集合竞价", "盘后定价", "竞价交易")
CHANNELS_LONGEST = tuple(sorted(CHANNELS, key=len, reverse=True))
CHANNEL_NEGS = ("不会通过", "不通过", "未通过", "不曾通过")
CHANNEL_SEPS = "、，,和及与或"
def _negated_channel_spans(clause):
    """T-R63b P2：从每个渠道否定短语起，向右整段标记「分隔符+渠道词」的运行段为否定。
    嵌套渠道词（「集中竞价交易」里的「竞价交易」）随整段一并标否；回看到否定短语起点，不按字数截断。"""
    spans = []
    for neg in CHANNEL_NEGS:
        start = clause.find(neg)
        while start >= 0:
            p = start + len(neg); end = p
            while True:
                q = end
                while q < len(clause) and clause[q] in CHANNEL_SEPS: q += 1
                hit = next((ch for ch in CHANNELS_LONGEST if clause.startswith(ch, q)), None)
                if hit is None: break
                end = q + len(hit)
            if end > p: spans.append((start, end))
            start = clause.find(neg, start + 1)
    return spans
def _has_affirmative_channel(clause):
    """同子句内是否存在未被渠道否定段覆盖的渠道词（T-R63b：以子句边界判定，不按 16 字回看）。"""
    spans = _negated_channel_spans(clause)
    for ch in CHANNELS:
        i = clause.find(ch)
        while i >= 0:
            if not any(a <= i < b for a, b in spans): return True
            i = clause.find(ch, i + 1)
    return False
def _mask_other_party(clause, groups):
    """T-R63b P1a：排除只抹掉「他方事件」跨度（动作词→事件词），不删整个子句——
    同子句里自身的风险词（如“债务逾期”）仍参与匹配（保守保留中间态）。
    组 = [动作词, 风险事件词]；只有主体判定为他方才抹：含自身称谓 → 不抹；
    含他方标记或公司名 → 抹；对象不明 → 不抹（宁误报不漏报，veto 场景有 FP 如实报告兜底）。"""
    spans = []
    for action, event in groups:
        i = clause.find(action)
        while i >= 0:
            j = clause.find(event, i + len(action))
            if j >= 0:
                mid = clause[i + len(action):j]
                if not any(s in mid for s in SELF_MARKERS) and (
                        any(o in mid for o in OTHER_MARKERS) or COMPANY_NAME.search(mid)):
                    spans.append((i, j + len(event)))
            i = clause.find(action, i + 1)
    if not spans: return clause
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    out, last = [], 0
    for a, b in merged:
        out.append(clause[last:a]); last = b
    out.append(clause[last:])
    return "".join(out)
def _occ_hit(clause, kw, negs, after=(), resets=(), window=10):
    """关键词在子句内的每次出现：前文（含关键词本身，允许“不减持”“无保留意见”重叠）有否定词且其后没有重置词，或后文有后置否定词 → 该次出现被否定；任一次未被否定 → 命中。
    T-R63b P2：否定词是渠道型（以「通过」结尾）时，只要同子句另有无否定的渠道词，就不否定本次出现。"""
    i = clause.find(kw)
    while i >= 0:
        pre, post = clause[:i + len(kw)], clause[i + len(kw):]
        neg_pos, neg_tok = -1, None
        for n in negs:
            if n == kw: continue
            p = pre.rfind(n)
            if p > neg_pos: neg_pos, neg_tok = p, n
        reset_pos = max((pre.rfind(r) for r in resets if r in pre[:i]), default=-1)
        negated = (neg_pos >= 0 and neg_pos > reset_pos) or any(0 <= post.find(x) <= window for x in after)
        if negated and neg_tok and neg_tok.endswith("通过") and _has_affirmative_channel(clause):
            negated = False
        if not negated: return True
        i = clause.find(kw, i + 1)
    return False
def _controller_equity(t, clauses, c, resets, w):
    """返回 (hit, flag)。flag ∈ {None, direction_down, direction_unknown, direction_up, neutral_change, subject_unknown}。"""
    t2 = t
    for n in c["subject_negations"]: t2 = t2.replace(n, "")
    subj = any(s in t2 for s in c["subjects"])
    if not subj:
        return False, ("subject_unknown" if "询价转让" in t else None)
    negs = c.get("negations_before", [])
    if any(_occ_hit(cl, k, negs, (), resets, w) for cl in clauses for k in c["down_words"]):
        return True, "direction_down"
    if any(k in t for k in c["up_words"]): return False, "direction_up"
    if any(k in t for k in c["change_terms"]):
        if any(k in t for k in c["direction_neutral_excludes"]): return False, "neutral_change"
        return (c["direction_unknown_policy"] == "conservative_hit"), "direction_unknown"
    return False, None
def _policy(t, excluded):
    """返回政策命中类别列表（保守否决口径，非事实判断）。"""
    out = []
    P = LEX["policy_rules"]
    if any(k in t for k in P["inquiry_transfer_policy"]["any"]): out.append("inquiry_transfer_policy")   # 优先于整条排除，无否定豁免
    c = P["concert_change_policy"]
    if (not excluded and any(s in t for s in c["require_any_subject"]) and all(k in t for k in c["require_all"])
            and any(e in t for e in c["require_any_event"]) and any(x in t for x in c["require_any_change"])):
        out.append("concert_change_policy")
    return out
def match_detail(title):
    t = norm(title)
    excluded = (not t) or bool(PREFIX.search(t)) or any(x in t for x in LEX["title_excludes"])
    pol = _policy(t, excluded) if t else []
    flags = {p: "policy_conservative" for p in pol}
    if excluded: return bool(pol), pol, flags
    clauses = [c for c in SPLIT.split(t) if c]
    cats = list(pol)
    rs = LEX.get("negation_resets", [])
    for name, c in LEX["categories"].items():
        negs = c.get("negations_before", []); aft = c.get("negations_after", []); w = c.get("after_window", LEX.get("after_window", 10))
        # T-R63b P1a：exclude_all_of 只抹掉「他方事件」跨度，不删整个子句（同子句自身风险词仍可命中）。
        exc = c.get("exclude_all_of") or []
        cat_clauses = [_mask_other_party(cl, exc) for cl in clauses] if exc else clauses
        cat_clauses = [cl for cl in cat_clauses if cl]
        if not cat_clauses: continue
        if c.get("type") == "controller_equity":
            ok, fl = _controller_equity(t, cat_clauses, c, rs, w)
            if fl: flags[name] = fl
        elif "require_all" in c:
            ok = any(r in t for r in c["require_any"]) and all(any(_occ_hit(cl, k, negs, aft, rs, w) for cl in cat_clauses) for k in c["require_all"])
        else:
            ok = any(_occ_hit(cl, k, negs, aft, rs, w) for cl in cat_clauses for k in c["keywords"])
        if ok: cats.append(name)
    return bool(cats), cats, flags
def match(title):
    h, c, _ = match_detail(title)
    return h, c
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
def _effective(x, trading_days):
    """带时区时刻 → 生效时刻（plan T-R22 裁定④：F23 每日冻结在 D 09:30，只判所属生效日）。
    交易日且时刻 < 09:30（含盘前）→ 当日 09:30；其余（含恰为 09:30、盘中、午休、11:30/15:00 边界、盘后、非交易日）→ 次一交易日 09:30。"""
    d = x.date().isoformat(); tod = x.timetz().replace(tzinfo=None)
    if d in trading_days and tod < OPEN_AM:
        return datetime.combine(x.date(), OPEN_AM, CST)
    return datetime.combine(date.fromisoformat(_next_td(trading_days, d)), OPEN_AM, CST)
def available_from_detail(t, first_seen_at, trading_days):
    """返回 (available_from, note)。available_from = 已知时间（t、first_seen_at）各自生效时刻的 max：不早于已知的首次观测，首次观测之后的信息不回流到过去。
    t 为纯日期（V7 实测如此）→ 次一交易日 09:30（plan F23“只有日期 → 次一交易日开盘”）；t 为带时区 datetime → 按 _effective。
    两者都未知 → (None, "unknown")。只知 t → note="t_only_pit_limited"：只是按披露时间推断的可得时点，不等于已保存的首次观测快照，回测有 PIT 局限。
    只知 first_seen_at → note="first_seen_only"。"""
    if t is None and first_seen_at is None: return None, "unknown"
    vals = []
    if first_seen_at is not None: vals.append(_effective(_aware(first_seen_at, "first_seen_at"), trading_days))
    if t is not None:
        if isinstance(t, datetime): vals.append(_effective(_aware(t, "t"), trading_days))
        elif isinstance(t, date): vals.append(datetime.combine(date.fromisoformat(_next_td(trading_days, t.isoformat())), OPEN_AM, CST))
        else: raise ValueError(f"t 类型不支持：{t!r}")
    note = "both" if (t is not None and first_seen_at is not None) else ("t_only_pit_limited" if first_seen_at is None else "first_seen_only")
    return max(vals), note
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
    2) 存在 available_from 未知（None：t 与 first_seen_at 都未知）的记录 → 返回 None；
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
