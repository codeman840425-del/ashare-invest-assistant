# 由 T-R15_golden.json 渲染两张正式卡片的 validation.fixtures（避免手抄误差）。仅研究侧辅助。
import json, pathlib, yaml
D = pathlib.Path(__file__).parent; G = json.loads((D / "T-R15_golden.json").read_text())
class F(list): pass
yaml.add_representer(F, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True))
def fl(o):
    if isinstance(o, dict): return {k: fl(v) for k, v in o.items()}
    if isinstance(o, list): return F(fl(v) for v in o) if all(not isinstance(v, (dict, list)) for v in o) else [fl(v) for v in o]
    return o
def dump(o): return yaml.dump(fl(o), allow_unicode=True, sort_keys=False, width=200)
for key in ("sw_ma_trend_pullback", "hold_risk_monitor"):
    src = (D / f"{key}.card.tmpl").read_text()
    v = yaml.safe_load((D / f"{key}.validation.yaml").read_text())
    v["fixtures"] = G["cards"][key]
    out = src.replace("<<VALIDATION>>", "```yaml validation\n" + dump(v) + "```")
    (D.parent / f"cards/{key}.md").write_text(out)
    print(key, len(G["cards"][key]))
