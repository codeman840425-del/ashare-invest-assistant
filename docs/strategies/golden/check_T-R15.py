# 按 plan 2.5.14 A–E/H 对两张卡做静态格式自检（研究侧辅助，非导入器）。
import re, sys, pathlib, yaml
D = pathlib.Path(__file__).resolve().parents[1]
CAT = set(re.findall(r"^\| F\d+ \| (f\.[a-z0-9_]+) \|", (D / "feature_spec.md").read_text(), re.M))  # 只认 §12 汇总表已登记的 F 条目
ENUM = dict(category={"trend","momentum","reversal","breakout","value","quality","dividend","low_vol","event","intraday_t","risk"},
  horizon={"intraday_t","short","swing","long"}, dim={"technical","capital","fundamental","sentiment","sector_market","news"},
  role={"entry","hold","weakening","exit","filter","veto","counter","invalidation"},
  state={"entry_ok","not_triggered","hold_ok","weakening","exit_signal","vetoed","insufficient_data"},
  action={"buy","add","hold","reduce","sell","wait"})
RC = set(re.findall(r"^\| `([A-Z0-9_]+)` \|", (D.parent / "api-contract.md").read_text(), re.M))
COMPAT = {"entry": {"entry"}, "counter_evidence": {"counter"}, "invalidation": {"invalidation"}, "exit": {"exit","hold","weakening"}}
err = []
for f in sorted((D / "cards").glob("*.md")):
    t = f.read_text(); E = lambda m: err.append(f"{f.name}: {m}")
    blk = {k: re.findall(rf"```yaml {k}\n(.*?)```", t, re.S) for k in ("strategy-card","strategy-spec","validation")}
    if len(blk["strategy-card"]) != 1 or len(blk["strategy-spec"]) > 1 or len(blk["validation"]) > 1: E("块数量"); continue
    c, s, v = (yaml.safe_load(blk[k][0]) for k in ("strategy-card","strategy-spec","validation"))
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", c["key"]) or c["key"] != s["key"]: E("key")
    if c["category"] not in ENUM["category"]: E("category")
    if not set(c["horizons"]) <= ENUM["horizon"]: E("horizons")
    if any(d["dimension"] not in ENUM["dim"] for d in c["dimensions"]): E("dimension")
    for d in c["data_needs"]:
        if d["feature_key"] not in CAT: E("data_needs 不在 catalog " + d["feature_key"])
    rules = {r["id"]: r for r in s["rules"]}
    exitonly = c.get("mount_policy") == "system_only"
    if "origin" in c: E("卡内不得有 origin")
    if re.search(r"to_quantify", blk["strategy-card"][0] + blk["strategy-spec"][0]): E("含 to_quantify")
    for lst in ("counter_evidence","invalidation","exit") + (() if exitonly else ("entry",)):
        if not c.get(lst): E("缺 " + lst)
        for it in c.get(lst, []):
            if it["ref"] not in rules or rules[it["ref"]]["role"] not in COMPAT[lst]: E(f"ref {it['ref']}")
    for r in s["rules"]:
        if r.get("status", "quantified") != "quantified": E("非 quantified 规则 " + r["id"])
        if r["role"] not in ENUM["role"] or r["dimension"] not in ENUM["dim"] or len(r["expr"]) > 300: E("rule " + r["id"])
        if r["role"] in ("entry","filter","veto","counter","invalidation") and re.search(r"\b(ctx|plan)\.", r["expr"]): E("ctx 用在非持仓角色 " + r["id"])
        if "_qfq" in r["expr"] and re.search(r"\b(plan\.(entry_price|stop_loss|take_profit)|ctx\.(cost_price|last_price|highest_close_since_entry))\b(?!_qfq)", r["expr"]): E("adjust_mismatch " + r["id"])
        for k in re.findall(r"\bf\.[a-z0-9_]+", r["expr"]):
            if k not in CAT: E("expr 键 " + k)
        for k in re.findall(r"\bp\.([a-z0-9_]+)", r["expr"]):
            if k not in s["params_schema"]: E("参数 " + k)
    for k, p in s["params_schema"].items():
        ty = {"int": int, "float": float}[p["type"]]
        if not all(type(p[x]) is ty for x in ("default","min","max","step")) or not p["min"] <= p["default"] <= p["max"]: E("param " + k)
    roles = {r["role"] for r in s["rules"]}
    if exitonly:
        if roles - {"exit","weakening","counter","invalidation"} or set(s["action_map"].values()) & {"buy","add"}: E("纯离场违规")
    elif not ({"entry","counter","invalidation"} <= roles and (s["stops"].get("stop_loss") or s["stops"].get("time_stop_days"))): E("G1")
    fx = v["fixtures"]
    if len(fx) < 6: E("fixtures<6")
    for x in fx:
        for k in list(x["features"]) + list(x.get("series", {})):
            if k not in CAT: E(f"{x['id']} 键 {k}")
        sec = x.get("security", {})
        if set(sec) != {"code","board","list_date"} or sec["board"] not in {"main","chinext","star","bse"}: E(x["id"] + " security")
        ex = x["expect"]
        if set(ex) - {"state","action","rule_ids_passed","reason_codes","lot_rule","reason_details"}: E(x["id"] + " expect 多余键")
        need = {c for c in ex.get("reason_codes", []) if c in ("LIMIT_LOCKED","SUSPENDED")}
        rd = ex.get("reason_details", {})
        if set(rd) != need or any(set(v) != {"direction"} or v["direction"] not in ("buy","sell") for v in rd.values()): E(x["id"] + " reason_details")
        if "lot_rule" in ex:
            lr = ex["lot_rule"]
            if not ({"min_buy","step","odd_lot_sell_all"} <= set(lr) <= {"min_buy","step","odd_lot_sell_all","sell_qty"}) or (lr["odd_lot_sell_all"] != ("sell_qty" in lr)): E(x["id"] + " lot_rule")
        if ex["state"] not in ENUM["state"] or ex["action"] not in ENUM["action"]: E(x["id"] + " enum")
        if exitonly and (ex["state"] not in {"hold_ok","weakening","exit_signal","insufficient_data"} or ex["action"] not in {"hold","reduce","sell"}): E(x["id"] + " 纯离场 state")
        if any(r not in RC for r in ex.get("reason_codes", [])): E(x["id"] + " reason_code")
        if any(r not in rules for r in ex["rule_ids_passed"]) or ex["rule_ids_passed"] != [r for r in rules if r in ex["rule_ids_passed"]]: E(x["id"] + " rule_ids 顺序")
        if not x["desc"].startswith("【虚构】"): E(x["id"] + " 未标虚构")
    if any(k in v for k in ("type","oos_result","benchmark","cost_model","trade_log_ref")): E("summary_key_in_validation")
    print(f.name, "fixtures", len(fx))
print("ERR" if err else "PASS", *err, sep="\n"); sys.exit(1 if err else 0)
