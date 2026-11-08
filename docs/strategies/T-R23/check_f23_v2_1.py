# T-R23 F23 词表 v2.1 离线检查（保守否决修订；研究侧；无网络、无麦蕊、不读 T-R22 隔离样本）。用法：python check_f23_v2_1.py
# PASS 只表示规则、用例与已知真值集一致，不代表验收；正式验收见 rules_freeze_v2_1.yaml（未执行）。
import pathlib, sys, hashlib, collections, yaml
D = pathlib.Path(__file__).parent; R22 = D.parent / "T-R22"; sys.path.insert(0, str(D))
class U(yaml.SafeLoader): pass
def _m(l, n, deep=False):
    ks = [l.construct_object(k, deep=deep) for k, _ in n.value]; assert len(ks) == len(set(ks)), f"重复键 {ks}"
    return yaml.SafeLoader.construct_mapping(l, n, deep)
U.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _m)
ld = lambda f: yaml.load((D / f).read_text(), Loader=U)
err = []
# 0 冻结：v2.1 新哈希；上一冻结 v2 记录与文件仍有效
for rec in ("rules_freeze.yaml", "rules_freeze_v2_1.yaml"):
    fz = ld(rec)
    for f, h in fz["sha256"].items():
        if hashlib.sha256((D / f).read_bytes()).hexdigest() != h: err.append(f"{rec} 哈希不符 {f}")
    if fz["holdout_acceptance"]["status"] != "not_executed": err.append("本轮不得声称已验收")
from match_f23_v2_1 import match, match_detail, LEX
# 1 v1 规则、v2 类别原样保留；PIT/计数代码与 T-R22 逐字一致
L1 = yaml.safe_load((R22 / "f23_lexicon_v1.yaml").read_text()); L2 = ld("f23_lexicon_v2.yaml")
if L2["categories"] != LEX["categories"]: err.append("v2 类别被改")
for k in ("title_excludes", "title_exclude_prefix_regex", "clause_split", "negation_resets", "dedup", "normalize", "after_window"):
    if LEX[k] != L1[k]: err.append(f"v1 全局规则被改 {k}")
tail = lambda p: p.read_text().split("from datetime import", 1)[1]
if tail(D / "match_f23_v2_1.py") != tail(R22 / "match_f23.py"): err.append("PIT/计数代码与 T-R22 不一致")
# 2 v1 153 例回归（有意变化同 v2：天力锂能）
INTENDED = {"天力锂能集团股份有限公司关于控股股东、实际控制人部分股份被司法变卖完成过户并解除质押、解除司法再冻结暨权益变动触及1%整数倍的提示性公告": True}
c1 = yaml.safe_load((R22 / "f23_offline_cases.yaml").read_text())["cases"]
for c in c1:
    if match(c["title"])[0] != INTENDED.get(c["title"], c["expect"]): err.append(f"v1 回归 {c['title']}")
# 3 v2.1 用例：policy_expect 与匹配一致；统计政策命中 vs 语义真值
cs = ld("f23_v2_1_cases.yaml")["cases"]
conf = collections.Counter()
for c in cs:
    got = match(c["title"])[0]
    if got != c["policy_expect"]: err.append(f"v2.1 例 {c['keyword']} {c['title']} 得 {match_detail(c['title'])}")
    conf[(c["policy_expect"], c["semantic_truth"])] += 1
for k in ("询价转让-中介文件(优先于排除)", "询价转让-澄清(优先于排除)", "询价转让-撤销/终止/不实施(无豁免)", "询价转让-普通股东", "一致行动到期/解除+权益变动", "一致行动到期/解除+权益变动(反例)"):
    if not any(c["keyword"] == k for c in cs): err.append(f"缺用例组 {k}")
# 4 完整已知真值集：v1 复用 10 + v2 新增 9 + v2.1 纳入 5 = 24，全部命中
known = []
for f in ("known_risk_v1_reused.yaml", "known_risk_v2_new.yaml", "known_risk_v2_1_added.yaml"): known += [(f, a) for a in ld(f)["announcements"]]
for f, a in known:
    if a["security_code"] == "301030": err.append("301030 不得计入")
    if not match(a["title"])[0]: err.append(f"漏 {f} {a['title']}")
    if str(a["announcement_date"]) in ("2026-11-04", "2026-11-05", "2026-11-06"): err.append("使用了预留/隔离日期 " + a["title"])
    if len(a["body_quote"]) > 80: err.append("短引超过 80 字 " + a["security_code"])
by = collections.Counter(f for f, _ in known)
print(f"known {len(known)} {dict(by)} | v1_regression {len(c1)} | v2.1_cases {len(cs)} policy/semantic: TP {conf[(True, True)]} 预计误报 {conf[(True, False)]} 漏 {conf[(False, True)]} TN {conf[(False, False)]} | holdout not_executed")
print("PASS（一致性，不代表验收）" if not err else "FAIL\n" + "\n".join(err))
