# T-A08 前端同步报告：契约 v0.2.7（fa6d55d）的 22 处分歧

- 提交：**d1fccf6**（只在本地，没有 push）。这个提交同时包含 T-F08 的评审修复，详见 `T-F08.md` 的“评审修复”一节。
- 改动范围只有 src/frontend/：没有改 docs、契约、后端、tests/、deploy/、.github/，原型目录也没动。
- `CONTRACT_VERSION = 'v0.2.7'`，示例数据横幅、mock 注释和契约自检测试已同步到这个版本。

## 22 处分歧逐项处理（编号对应 T-A08.md 第 3 节；第 17 项无分歧）

| # | 内容 | 处理 |
|---|---|---|
| 1 | 搜索 | 新增 `/securities/search` 和 `SecurityHit` 扩展字段。顶栏搜索改用新端点，不分页，最多 20 条，按服务端的 match_kind 顺序显示。mock 的 types 只接受 stock/cdr/index，其他值返回 400；q 超长返回 400。 |
| 2 | 上市状态 / 停牌 | 改用 `listing_status`（不是 listed 时显示标签）和 `suspended: boolean\|null`。 |
| 3 | 风险标记 | 改用 `risk_flag`（ST / *ST / 退）。 |
| 4 | 行业 / 概念 | 行业改为 `{taxonomy, code, name}`，概念改为 `[{code, name}]`。 |
| 5 | board 可为 null | 指数的 board 为 null，显示 “—”。 |
| 6 | 档案新增字段 | 补齐 type、list_date_basis、delist_date、former_names、code_history、master_as_of、attribution、sources。attribution 原样展示。 |
| 7 | 财务字段 | 补齐 report_period、available_from、is_restated、deducted_net_profit、bvps。 |
| 8 | 资金流 | 分档净额可为 null（显示 “—”），并加上 amount 和 is_final。 |
| 9 | 因子分组 | 改用 `category: factor_category`。键名要等 T003，枚举暂不列入，未知键原样显示。 |
| 10 | 因子分位 | 改用 `market_rank` 和 `market_rank_pct`，去掉行业分位。 |
| 11 | 因子集版本 | 改用 `factor_set_version` 和 `counts`。 |
| 12 | 公告 | `announcement_category` 枚举，加上 category_raw、level_raw、url_host、file_format、first_seen_at。展示响应里的 disclaimer。链接不在白名单时只显示域名。 |
| 13 | 板块资金 | 改用 `sector_code` 和 `amount`，响应带 taxonomy。 |
| 14 | 板块资金刷新 | 去掉 60 秒轮询，改为盘后数据；缓存 10 分钟，ETag 交给浏览器处理。 |
| 15 | 周 K mock | 第一根的 pre_close 取当周首日日线的 pre_close。is_final 只在该周已结束且日 K 都已最终时为 true。整周停牌不出 bar。 |
| 16 | 复权基准日 | bars 带 `adjust_as_of`。基准日变化时，`syncAdjustAsOf` 丢弃同证券、同复权方式的其他缓存，以便整段重载。有单元测试。 |
| 18 | StrategyInstance | 按 §5.1 的完整结构替换。 |
| 19 | risk_level | 列表中改为必有字段。 |
| 20 | 状态转换 mock | 转到当前所在状态时幂等返回 200。非法转换返回 409 INVALID_STATE_TRANSITION，带 `{from, to, allowed}`。`origin=system` 不能归档（409）。版本不可运行时返回 409 STRATEGY_VERSION_NOT_RUNNABLE。 |
| 21 | 实例列表 mock | 支持多值 status 和 origin 筛选、order 排序，以及带签名的游标；筛选或排序与游标不一致时返回 400 INVALID_CURSOR。 |
| 22 | “查看全部”去向 | 8 个去向按 §7.3 去向表（`pages/today/todayRoutes.ts`），测试直接解析契约表格比对。还没实现的目标页由占位页接住 tab、status、event 参数。 |
| 23 | /today 新字段 | 新增 alerts、plan_triggers、data_gaps、evidence 和 risk_event_id，页面新增三块（见 T-F08.md）。 |

新增测试 `src/pages/t-a08.test.tsx`，共 12 个测试，覆盖状态机、游标、搜索、adjust_as_of 和 is_final、基准日缓存，以及 5 个目标页接住参数。其余项由已有测试覆盖：t-f03、t-f22、t-f22a、contract.test 和 review-fixes.test 都已同步。

## 验证
- 工作区和干净检出（HEAD=d1fccf6）都按 CI 顺序全部通过：
  - lint 0 警告，typecheck 通过，vitest 20 个文件、322 个测试全部通过。
  - audit 只有 1 个 moderate，没有 high。
  - `build` 后运行 `check:dist`：示例标记 0 命中；`build:mock` 后反向自检：找到 19 个示例标记。
  - `check_ignored_sources` 错误 0。
- 扫描结果见 T-F08.md：工作区和暂存区都是 0 命中，暂存区只含 src/frontend/。

## 遗留问题（没有改契约）
1. **契约 v0.2.8 在本任务进行中落库（6ef79c4，06:54）。** 按“全部按 v0.2.7”的要求，前端仍对齐 v0.2.7，只同步了一处：`IMPORT_LOT_SIZE_IRREGULAR` 的处理文案（ETF 按 100 份整数倍）。原因是读 docs 的测试按 HEAD 的契约比对，不同步会失败。以下 v0.2.8 内容还没有同步，需要决定是否开一个 v0.2.8 同步任务：
   - ETF 的 security_type；
   - gap_reason `not_applicable`；
   - 搜索默认类型 stock,cdr,etf；
   - IngestLicenceStatus 和 AdminDataLicence 的 licence_id；
   - 证书暂停期间 PUT 的规则；
   - `/meta/enums.version`。

   其中蜜罐字段（#11）在 T-F24 中实现。
2. **factor_category 键名要等 T003 补测。**
3. **`/alerts` 和 `/plans` 的列表端点、页面要等 Q9。** 目前用占位页。
4. **`ProviderRef.endpoint` 在 mock 中为 null。** 契约没有给出各字段对应的麦蕊端点名。
5. **TodayAlert 的 more 写法和去向表不一致**（`/alerts?status=new,read` 对 `/alerts`）。前端按去向表的“前端路由”列实现。
6. **风险提示的 evidence_ids 不保证在 `/today.evidence` 中。**
