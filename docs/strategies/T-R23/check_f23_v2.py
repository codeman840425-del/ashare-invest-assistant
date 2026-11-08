# T-R23 F23 词表 v2 离线检查（研究侧；无网络、无麦蕊、不读 T-R22 隔离样本）。用法：python check_f23_v2.py → PASS/FAIL
# PASS 只表示规则、用例与已知清单一致，不代表正式验收；正式验收见 rules_freeze.yaml holdout_acceptance（未执行）。
import pathlib, sys, collections, hashlib, yaml
D = pathlib.Path(__file__).parent; R22 = D.parent / "T-R22"; sys.path.insert(0, str(D))
class U(yaml.SafeLoader): pass
def _m(l, n, deep=False):
    ks = [l.construct_object(k, deep=deep) for k, _ in n.value]; assert len(ks) == len(set(ks)), f"重复键 {ks}"
    return yaml.SafeLoader.construct_mapping(l, n, deep)
U.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _m)
for f in ("f23_lexicon_v2.yaml", "f23_v2_cases.yaml", "known_risk_v2_new.yaml", "known_risk_v1_reused.yaml", "title_insufficient.yaml", "rules_freeze.yaml"): yaml.load((D / f).read_text(), Loader=U)
err = []
# 0 冻结哈希
fz = yaml.safe_load((D / "rules_freeze.yaml").read_text())
for f, h in fz["sha256"].items():
    if hashlib.sha256((D / f).read_bytes()).hexdigest() != h: err.append(f"冻结哈希不符 {f}")
if fz["holdout_acceptance"]["status"] != "not_executed": err.append("本轮不得声称已验收")
from match_f23_v2 import match, match_detail, LEX
# 1 v1 词与规则原样保留；PIT/计数代码与 T-R22 逐字一致（由 T-R22/check_f23.py 覆盖其测试）
L1 = yaml.safe_load((R22 / "f23_lexicon_v1.yaml").read_text())
for name, c in L1["categories"].items():
    for k, v in c.items():
        if k == "keywords":
            if not set(v) <= set(LEX["categories"][name]["keywords"]): err.append(f"v1 关键词缺失 {name}")
        elif LEX["categories"][name][k] != v: err.append(f"v1 规则被改 {name}.{k}")
for k in ("title_excludes", "title_exclude_prefix_regex", "clause_split", "negation_resets", "dedup", "normalize", "after_window"):
    if LEX[k] != L1[k]: err.append(f"v1 全局规则被改 {k}")
n1 = sum(len(c.get("keywords", [])) for c in L1["categories"].values()) + 1
if n1 != 51: err.append(f"v1 词数应为 51，得 {n1}")
tail = lambda p: p.read_text().split("from datetime import", 1)[1]
if tail(D / "match_f23_v2.py") != tail(R22 / "match_f23.py"): err.append("PIT/计数代码与 T-R22 不一致")
# 2 v1 153 例回归：除列明的有意变化外期望不变
INTENDED = {"天力锂能集团股份有限公司关于控股股东、实际控制人部分股份被司法变卖完成过户并解除质押、解除司法再冻结暨权益变动触及1%整数倍的提示性公告": True}
c1 = yaml.safe_load((R22 / "f23_offline_cases.yaml").read_text())["cases"]
for c in c1:
    exp = INTENDED.get(c["title"], c["expect"])
    if match(c["title"])[0] != exp: err.append(f"v1 回归 {c['title']}")
# 3 v2 新增规则正反例与覆盖（每个新增关键词 ≥2 正 1 反）
c2 = yaml.safe_load((D / "f23_v2_cases.yaml").read_text())["cases"]
tally = collections.defaultdict(lambda: [0, 0])
for c in c2:
    if match(c["title"])[0] != c["expect"]: err.append(f"v2 例 {c['keyword']} {c['title']} 得 {match_detail(c['title'])}")
    tally[c["keyword"]][0 if c["expect"] else 1] += 1
new_kws = [k for n, c in LEX["categories"].items() for k in c.get("keywords", []) if k not in L1["categories"].get(n, {}).get("keywords", [])]
for k in new_kws + ["询价转让"]:
    if tally[k][0] < 2 or tally[k][1] < 1: err.append(f"覆盖不足 {k} {tally[k]}")
for k in ("权益变动-上升(反例)", "权益变动-中性(反例)", "权益变动-无主体(反例)", "权益变动-否定(反例)", "解除一致行动(反例)"):
    if tally[k][1] < 1: err.append(f"缺反例 {k}")
# 4 已知风险：v1 复用 12 条 + v2 新增，全部命中；301030 不计；日期避开预留/隔离日
known = yaml.safe_load((D / "known_risk_v1_reused.yaml").read_text())["announcements"] + yaml.safe_load((D / "known_risk_v2_new.yaml").read_text())["announcements"]
for a in known:
    if a["security_code"] == "301030": err.append("301030 不得计入")
    if not match(a["title"])[0]: err.append("漏 " + a["title"])
    if str(a["announcement_date"]) in ("2026-11-04", "2026-11-05", "2026-11-06"): err.append("使用了预留/隔离日期 " + a["title"])
    if len(a["body_quote"]) > 80: err.append("短引超过 80 字 " + a["security_code"])
# 5 标题不足例：按冻结规则不计且带标记（记录局限，不冒充正文可判）
ti = yaml.safe_load((D / "title_insufficient.yaml").read_text())["items"]
for a in ti:
    h, _, fl = match_detail(a["title"])
    if h or fl.get("controller_equity") != a["v2_flag"]: err.append(f"标题不足例行为不符 {a['code']} {h} {fl}")
nv1 = sum(1 for a in known if a in yaml.safe_load((D / "known_risk_v1_reused.yaml").read_text())["announcements"])
print(f"v1_words {n1} new_words {len(new_kws)} v1_regression {len(c1)} (intended_changes {len(INTENDED)}) v2_cases {len(c2)} known {len(known)} (v1 {nv1} + v2 {len(known) - nv1}) title_insufficient {len(ti)} holdout {fz['holdout_acceptance']['status']}")
print("PASS（一致性，不代表验收）" if not err else "FAIL\n" + "\n".join(err))
