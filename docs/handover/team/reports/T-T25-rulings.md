# T-T25 架构师裁定（market_rules 同步 T-R10 + §7.9 七个待定问题）

- 提交：`46538a6`（本地，基于 `bff4a62`，只改 `docs/plan.md`、`docs/api-contract.md`；未推送）
- 契约版本不变（v0.2.9），变更表追加 #32「v0.2.9 内，T-T25」
- 检查：check_contract.py 通过；check_code_namespaces.py 通过；`contract_md.enums()` = 84（不变）；`gitleaks dir docs` no leaks
- 新增产品问题编号：**无**（7 条都是技术问题或已有用户结论下的保守口径；第 9 节最大号仍为 89）
- 未改 `docs/strategies/`，未写任何 licence 值，未调用麦蕊

## 一、plan §6.1 market_rules 同步 T-R10

- 两段（2026-07-06、2023-04-10）`lot` 增加 8 键：`odd_lot_sell_all`、`star_odd_lot_threshold: 200`、`max_order_qty: 1000000`、`star_max_limit_order: 100000`、`star_max_market_order: 50000`、`star_max_after_hours: 1000000`、`chinext_max_limit_order: 300000`、`chinext_max_market_order: 150000`；`t_plus` 后加 `t0_round_trip` 块（`fund_categories` 6 类、`cross_border_requires_t0_constituents: true`、`unknown_category_default_t_plus: 1`、`data_source: null`）。
- 注释按 T-R10 更新：`star_min_buy` 买卖均适用（2026 段沪第 6.7 条 / 2023 段第 6.1.7 条）；`star_step` 改为【部分核实】；北交所改为【未核实】；2023 段盘后上限引沪 2023 第 6.2.6 条。
- `data_source` 注释改为引 plan 2.13（接入前全部 ETF 按 T+1，以本键非空为前提，T-O11），不再引 reports 文件。
- 校验：plan 块解析后与后端 `config/market_rules.yaml`（07b8d74）**完全相等**，与测试快照 `tests/backend/api_app/config_defaults/market_rules.yaml`（e5fb12c）**完全相等** → `test_snapshot_equals_plan_block[market_rules]` 的 T-R10 xfail 应转为通过。
- 2.13「交易单位」行重写：买入单位（科创板 ETF 按 100 份）、零股卖出 V1 判定（按可卖数量 A：q%100==0 或 q==A；科创板 A≥200 时 200≤q≤A，A<200 只能 q=A）、单笔申报上限，草案数量超上限时截断并提示（与 50 万股风险警示上限同一做法）。T-T19 测试要点补零股、科创板 ETF、单笔上限、data_source 为空时 T+1。问题 86 标注“T-R10 已核对，与规则一致”。契约 §7.7 零股规则同样标注。

## 二、七个待定问题

| # | 问题 | 结论 | 写入位置 |
|---|---|---|---|
| 1 | R11 #9/#10 是否也作为例外 | **是，但只放行一个错误码 + field**：#9 `POST /trades` 格式合法但推断不出市场 → `400 VALIDATION_ERROR`（`field: security_code`）；#10 `PUT /imports/{batch_id}/options` 解析器与批次 kind 不符 → `400 VALIDATION_ERROR`（`field: parser_id`）。`qty`/`price`/`encoding_override` 的格式错误**不是**例外，由后端收紧 schema（pattern / 内联取值）解决，后端落地前这些用例照常失败 | plan 8.0「契约」行 |
| 2 | `schemathesis.toml` 归属 | 位置不变（`src/backend/schemathesis.toml`，CI 在 src/backend 下读取），**归后端维护**；例外的唯一清单是 `tests/backend/contract/r11_exceptions.py`，**归测试员维护**；toml 中每条例外必须能在登记表中找到，测试员加只读一致性用例 | plan 8.0「契约」行 |
| 3 | 冷却契约写 202 是否确认 | **确认 202 不变**：冷却中重复 PUT 同一证书、删除后到期前重提同一证书 → `202` 与当前状态，不投递验证（#12/#13、§7.1 PUT 行原文） | 契约 #32 ① |
| 4 | trigger 威胁模型范围 | 数据库属主 / 超级用户 / 能执行 DDL 的角色**不在**删除 CLI 威胁模型内（本来就能直接读全部数据）。作为防误配的完整性检查：CLI 在 dry-run 与 `--execute` 前只读列出清单内表上的非内部触发器，与代码中白名单（表 + 触发器名 + 函数名）比对；dry-run 报差异，`--execute` 遇白名单外触发器拒绝执行、非零退出，无跳过参数；不检查函数体、不检查清单外表 | plan 7.3 删除 CLI 规则 |
| 5 | 裁定 A 的 24h 边界（含/不含） | **半开区间，不含端点**：到期时刻 = `paused_until`（非 null）或删除时刻 + 24h（null）；仅当 now < 到期时刻有效，now = 到期时刻即过期；“paused_until 未到期”同样指 now < paused_until，恰好相等按到期后的新提交处理；用数据库 UTC 时间比较 | plan 7.3 周期清理；契约 §7.1 DELETE 行、#32 ① |
| 6 | R6 有快照参考价但不在主数据中的行 | **保守：不采用快照价**。`security_type=null` 的行一律按成本估算：`estimated=true`，`market_value`/`pnl`/`pnl_pct` 为 null（价格口径与单位无法对照主数据核实，如可转债面值 100 元/张）。现价来源链（日线收盘 → 快照参考价）只适用于主数据内的行。与用户已定的 U3、问题 79 一致，故不新编号 | 契约 §7.2 `/portfolio`、#32 ② |
| 7 | R8 trigger `on_demand` 不在 CHECK 中 | **后端缺陷**：迁移 0002 的 CHECK 是 `import/watchlist_add/weekly/position_open_close`，缺 `on_demand`；后端新增迁移补上，downgrade 前若有 `on_demand` 行则拒绝降级；plan 3.3 写明库级 CHECK 必须与 trigger 列表完全一致 | plan 3.3 `symbol_horizon_assessments` 行 |

## 三、各角色待办

**后端**
1. 新迁移：`ck_symbol_horizon_assessments_trigger` 加入 `on_demand`（#7）；GET 同步计算落库时 `trigger='on_demand'`。
2. 删除用户数据 CLI（T-B16）：触发器白名单自检（dry-run 列差异，`--execute` 拒绝执行）；白名单随迁移维护（#4）。
3. 证书冷却（T-B04a-x / cooldown-purge）：到期判定改为 `now < expires_at`（数据库 UTC），`expires_at` 按 #5 取值；PUT 的“paused_until 未到期”同口径（#5）。
4. `/portfolio`（T-B46-x）：`security_type=null` 的行不读快照参考价（#6）。
5. R11 #9/#10 的 schema 收紧：`TradeCreate.qty/price` pattern、`security_code` pattern、`encoding_override` 内联取值（#1）；`schemathesis.toml` 的例外与测试员登记表保持一致（#2）。
6. market_rules：plan 块已与 `config/market_rules.yaml` 解析后相等，无需改值；如需逐字一致，可把两处 `data_source` 注释改为 plan 写法（可选）。草案数量按单笔上限截断并提示（2.13）；`fund_t_plus` 以 `data_source` 非空为闸门（T-O11 m④，既有）。

**测试员**
1. `r11_exceptions.py` 登记 R11-9、R11-10（方法 + 路径 + 400 + `VALIDATION_ERROR` + field），自检用例确保同接口其他 400 仍失败（#1）。
2. 加只读一致性用例：`src/backend/schemathesis.toml` 的每条例外都在登记表中（#2）。
3. 冷却边界用例：now = 到期时刻 → 过期（按新提交处理）；now = 到期前 1 秒 → 有效（#5）。
4. `test_integration_t_t25c.py` O_PURGE_TRIGGERS：断言改为“白名单外触发器 → dry-run 列出、`--execute` 非零退出且不删任何行”；不再要求防御属主级攻击（#4）。
5. `test_r6_not_in_master_snapshot_priced`：期望改为 `security_type=None`、`estimated=True`、`market_value/pnl/pnl_pct=None`、`weight_pct` 按成本，`gaps` 含 `positions.convertible_bond`（113xxx 属可转债段）（#6）。
6. R8：保留 `on_demand` CHECK 的 xfail（owner 后端，#7）。
7. market_rules：去掉 `TR10_PLAN_PENDING` xfail，`test_snapshot_equals_plan_block[market_rules]` 改严格；T-T19 补 2.13 新增测试要点。

**前端**：无改动（`security_type=null` 行本来就显示“不在主数据·估算”、市值“—”）。

**研究员**：无新增；北交所交易单位仍【未核实】（V1 不扫描）。

**运维**：推送时 `46538a6` 随 docs 一并推送（只含文档）；无部署项。
