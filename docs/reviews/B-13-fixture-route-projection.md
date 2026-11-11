# B-13：B-03 十九场景与五端点响应投影核对

2026-11-11（北京时间）。按 Chief 第五批派单，只交字段与行为差异文档；本次提交不包含路由、夹具或测试代码修改。

## 冻结范围与结论

| 资源 | PR | 冻结 head |
|---|---|---|
| B-03 输入 | [#51](https://github.com/codeman840425-del/ashare-invest-assistant/pull/51) | `9af5b7341dc0cb4f9220ac3459d5a629f9437dfe` |
| bars | [#56](https://github.com/codeman840425-del/ashare-invest-assistant/pull/56) | `5e6356572a9eaec19b71ddd998b566fed4bec4b3` |
| financials | [#58](https://github.com/codeman840425-del/ashare-invest-assistant/pull/58) | `bd85f061405f7b4ece40fd5e6c1c75568985b9de` |
| fund-flows | [#59](https://github.com/codeman840425-del/ashare-invest-assistant/pull/59) | `b8794af2e20939fc9773d5d0d9cf9008affe9b3f`（含 P2 修复） |
| announcements | [#63](https://github.com/codeman840425-del/ashare-invest-assistant/pull/63) | `cef9de0317a2139b59557815aed3732cef1e6dc0` |
| factors | [#71](https://github.com/codeman840425-del/ashare-invest-assistant/pull/71) | `c7c97794604f6bf25e2a0f7a3d5e8939e9843a0b` |

首次采集时六个 head 已与 GitHub PR 实况核对；实现 PR 的 base 均为 `465e02046fa8d971897603742497444f884e89a2`。本文件也独立从此 main 基线建支。

采集后 #63 按 Chief 紧急派单追加链接安全返修 `3a147011084bdb75b9ba72ab729b5c087240f74f`；新增复跑公告原三场景，字段模式与三份响应均与首次证据相同。P1/P2 修复、44项定点与浏览器解析证据另见[返修报告](https://github.com/codeman840425-del/ashare-invest-assistant/blob/3a147011084bdb75b9ba72ab729b5c087240f74f/docs/handover/team/reports/B-05-announcements-P1P2.md)，独立复核销项不由本表替代。

- 五份 fixture SHA256 与 B-03 manifest 一致，并与各端点 worktree 的对应 fixture 字节相同；没有用重写输入来消除偏差。
- 19/19 原夹具可通过对应真实路由的 Pydantic 模型，JSON 往返后值不变；124 个字段路径（含容器）均无增删，字段必填性不变。
- 本地显式安装原作者 fixture reader 后，经注册 ASGI 路由发送原场景请求：19/19 返回 200，13/19 响应与原输入逐值相等。其余六场景全部列在下表；这不是生产数据源验收。
- factors 的原输入虽能通过响应模型，却不满足 #71 的路由空态守卫；直接将原 stock 输入送入真实处理函数会返回 500 `INTERNAL_ERROR`，响应不含合成版本或因子行。模型通过不能代替路由语义通过。

## 十九场景投影矩阵

| 资源 / 场景 | 原输入到本地 fixture HTTP 的结果 | 判定与接续 |
|---|---|---|
| bars / stock | 仅 `data_as_of` 从 `2026-11-03T15:40:00+08:00` 改为 `2026-11-02T15:00:00+08:00`；两根 K 线及其他字段相同 | 采用最早实际选用收盘时点；B-03 的合成抓取时间不能作为该路由预期值 |
| bars / licence_unavailable | 逐值相等；空行、null 时点、`data_licence_unavailable` | 原夹具可作当前本地 reader 预期 |
| bars / pending | 逐值相等；空行、null 时点、`quota_deferred` | 原夹具可作当前本地 reader 预期；不证明生产排队已接入 |
| bars / minute | 原一根合成 1m 行变为空；`fresh→unavailable`、`data_as_of/pre_close→null`，新增 `no_source` gap | #56 的 fixture reader 只支持日 K 不复权，1m 仅模型形状可复用；原非空 1m 不能作为该 HTTP 成功数据预期 |
| financials / stock | 逐值相等；16 个期间字段均保留 | 原夹具可作当前本地 reader 预期 |
| financials / licence_unavailable | 逐值相等；空行、空 sources、null 时点 | 同上 |
| financials / etf | 逐值相等；`not_applicable` | 同上 |
| financials / index | 逐值相等；`no_source` | 同上 |
| fund-flows / stock | 逐值相等；两日升序、Decimal 字符串与第二日 null 保留 | 原夹具可作当前本地 reader 预期 |
| fund-flows / licence_unavailable | 逐值相等；`data_licence_unavailable` | 同上 |
| fund-flows / etf | 逐值相等；`not_applicable` | 同上 |
| fund-flows / index | 逐值相等；`no_source` | 同上 |
| announcements / stock | 逐值相等；两条标题/链接元数据倒序、非白名单 URL=null、固定免责全文 | 原夹具可作无筛选、无翻页的当前本地 reader 预期 |
| announcements / licence_unavailable | 逐值相等；空行、空 sources、null 时点、null cursor | 同上 |
| announcements / etf | 逐值相等；`not_applicable`，无 security_code/name 顶层字段 | 同上；B-03 没有独立公告 index 场景 |
| factors / stock | 两条合成行→空、counts 2→0、分类计数→{}、sources→[]、`partial→unavailable`、时点/版本/无请求日期→null、gap→`factors/no_source` | 按 T-A158 有意投影；只复用原输入，禁止把原非空响应作为 HTTP 预期 |
| factors / licence_unavailable | 版本/无请求日期→null；原证书 gap→`no_source`，message 改为本地投影说明 | 当前 #71 本地 reader 与默认 reader 只提供无源空态，尚未实现证书状态读取；原证书场景不是一比一语义覆盖 |
| factors / etf | 版本/无请求日期→null；`not_applicable` 保留，message 改为本地投影说明 | 按 T-A158 空态投影 |
| factors / index | 版本/无请求日期→null；`no_source` 保留，message 改为本地投影说明 | 按 T-A158 空态投影 |

## 偏差清单与复用边界

1. **D1，bars 日 K 时点：已知修正。** [B-04 reader:51](https://github.com/codeman840425-del/ashare-invest-assistant/blob/5e6356572a9eaec19b71ddd998b566fed4bec4b3/src/backend/selfchecks/b04_source.py#L51) 明确按最早选中收盘时点生成 `data_as_of`。前端 F-08/#57 已以 #56 为语义依赖；复用 B-03 时须比较投影结果，不能坚持旧抓取时间。
2. **D2，bars 1m 非空：当前打样未覆盖。** 同 reader:37 对 `freq!=d` 或 `adjust!=none` 直接返回空态，禁止把日 K 重贴为分钟/复权数据。B-03 的 1m 非空场景只证明模型可容纳该形状；若后续需要真实 HTTP 非空分钟链，须 Chief 另派读取源实现与验收。
3. **D3，factors 全四场景：裁定后的有意投影。** [T-A158 裁定:8](https://github.com/codeman840425-del/ashare-invest-assistant/blob/f048f4a/docs/reviews/T-A158-factors-empty-state-ruling.md#L8) 规定请求日期透传、无请求无批次 null、无真实版本 null。B-03 的四个场景都保留旧日期和合成版本，不能直接作为 #71 的期望响应；stock 的两行和分类也必须归零。无请求日期的四场景已在本次投影核对；显式请求日期由 #71 既有默认/本地两组 × stock/ETF/index 定点承担，B-03 本身没有该用例。
4. **D4，factors 证书不可用：覆盖降为无源空态。** [本地 reader:36](https://github.com/codeman840425-del/ashare-invest-assistant/blob/c7c97794604f6bf25e2a0f7a3d5e8939e9843a0b/src/backend/selfchecks/test_b05_factors.py#L36) 按证券类型投影，无证书状态分支；默认 reader 同样只查询公开证券身份。不得据这行宣称证书失效、读取本人缓存或跨证书回退的生产链已验收。真正接入本人数据源时另列定点，不改写 T-A158 空态口径。
5. **D5，模型约束有七处差异，当前有效样本无投影丢值。** 五处日期正则约束在路由模型变为普通字符串：bars.adjust_as_of、financials.items[].period_end/announce_date/available_from、fund-flows.items[].trade_date。另两处是 T-A158 授权的 factors.trade_date/factor_set_version 可空化。B-03 校验器还包含排序、OHLC、资金桶勾稽、合成开市日与URL白名单等独立语义守卫；这些不由“响应模型接受”自动证明，保留各端点相关自检责任。另 B-03 Shape 使用 `strict=True`，B-05 Shape 仅设置 `extra=forbid`；本表比较 JSON 字段类型，不宣称两者的 Python 输入强制转换行为相同。
6. **D6，生产默认源与本地夹具的能力不同。** 五端点默认源都只读公开证券身份并给无源空态，B-03 非空样例仅在 local/test 显式注入。fund-flows 原场景无 from/to，不能替代 #59 的 250/251 开市日与日历缺口详情负例；公告原场景 next_cursor 全为 null，不能替代 #63 的签名游标范围、翻页及链接守卫。B-06/r2 与生产接入均未执行。

以上偏差不要求本单修改路由。D1/D3 按既有实现/裁定消费；D2/D4 是后续源接入时应保留的覆盖缺口。合入者仍须保留五个路由注册并验证共存，本次按独立 PR 运行，没有做集成试合。

## 逐字段模式对照

每行列出 B-03 字段与该 PR 响应模型的类型；`null` 表示字段值可空，所有行字段仍为必填。数组、对象和映射容器也各计一路径，因此总计124路径，不等同于124叶字段。枚举和值域复用现有枚举；Decimal 均为 JSON 字符串，不转 JSON number。

### bars

| 字段路径 | B-03 | 真路由模型 | 结果 |
|---|---|---|---|
| `data_status` | enum(fresh,stale,pending,partial,unavailable) | enum(fresh,stale,pending,partial,unavailable) | 一致 |
| `data_as_of` | string / null | string / null | 一致 |
| `gaps` | array | array | 一致 |
| `gaps[].key` | string | string | 一致 |
| `gaps[].reason` | enum(no_source,not_yet_published,upstream_error,quota_deferred,user_input_missing,data_licence_unavailable,not_applicable) | enum(no_source,not_yet_published,upstream_error,quota_deferred,user_input_missing,data_licence_unavailable,not_applicable) | 一致 |
| `gaps[].message` | string | string | 一致 |
| `security_code` | string | string | 一致 |
| `name` | string | string | 一致 |
| `freq` | enum(1m,d,w) | enum(1m,d,w) | 一致 |
| `adjust` | enum(none,qfq,hfq) | enum(none,qfq,hfq) | 一致 |
| `pre_close` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `adjust_as_of` | 日期格式字符串 / null | string / null | 类型差异，见D5 |
| `next_before` | string / null | string / null | 一致 |
| `items` | array | array | 一致 |
| `items[].t` | string | string | 一致 |
| `items[].open` | Decimal字符串 | Decimal字符串 | 一致 |
| `items[].high` | Decimal字符串 | Decimal字符串 | 一致 |
| `items[].low` | Decimal字符串 | Decimal字符串 | 一致 |
| `items[].close` | Decimal字符串 | Decimal字符串 | 一致 |
| `items[].pre_close` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].volume` | Decimal字符串 | Decimal字符串 | 一致 |
| `items[].amount` | Decimal字符串 | Decimal字符串 | 一致 |
| `items[].avg_price` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].is_final` | boolean | boolean | 一致 |

### financials

| 字段路径 | B-03 | 真路由模型 | 结果 |
|---|---|---|---|
| `data_status` | enum(fresh,stale,pending,partial,unavailable) | enum(fresh,stale,pending,partial,unavailable) | 一致 |
| `data_as_of` | string / null | string / null | 一致 |
| `gaps` | array | array | 一致 |
| `gaps[].key` | string | string | 一致 |
| `gaps[].reason` | enum(no_source,not_yet_published,upstream_error,quota_deferred,user_input_missing,data_licence_unavailable,not_applicable) | enum(no_source,not_yet_published,upstream_error,quota_deferred,user_input_missing,data_licence_unavailable,not_applicable) | 一致 |
| `gaps[].message` | string | string | 一致 |
| `sources` | array | array | 一致 |
| `sources[].provider` | enum(mairui,user_import,user_input,system,exchange) | enum(mairui,user_import,user_input,system,exchange) | 一致 |
| `sources[].endpoint` | string / null | string / null | 一致 |
| `sources[].fetched_at` | string / null | string / null | 一致 |
| `security_code` | string | string | 一致 |
| `name` | string | string | 一致 |
| `items` | array | array | 一致 |
| `items[].period_end` | 日期格式字符串 | string | 类型差异，见D5 |
| `items[].report_period` | enum(q1,h1,q3,fy) | enum(q1,h1,q3,fy) | 一致 |
| `items[].announce_date` | 日期格式字符串 / null | string / null | 类型差异，见D5 |
| `items[].available_from` | 日期格式字符串 / null | string / null | 类型差异，见D5 |
| `items[].is_restated` | boolean | boolean | 一致 |
| `items[].revenue` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].revenue_yoy_pct` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].net_profit` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].net_profit_yoy_pct` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].deducted_net_profit` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].eps` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].bvps` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].roe_pct` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].gross_margin_pct` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].debt_ratio_pct` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].operating_cash_flow` | Decimal字符串 / null | Decimal字符串 / null | 一致 |

### fund-flows

| 字段路径 | B-03 | 真路由模型 | 结果 |
|---|---|---|---|
| `data_status` | enum(fresh,stale,pending,partial,unavailable) | enum(fresh,stale,pending,partial,unavailable) | 一致 |
| `data_as_of` | string / null | string / null | 一致 |
| `gaps` | array | array | 一致 |
| `gaps[].key` | string | string | 一致 |
| `gaps[].reason` | enum(no_source,not_yet_published,upstream_error,quota_deferred,user_input_missing,data_licence_unavailable,not_applicable) | enum(no_source,not_yet_published,upstream_error,quota_deferred,user_input_missing,data_licence_unavailable,not_applicable) | 一致 |
| `gaps[].message` | string | string | 一致 |
| `sources` | array | array | 一致 |
| `sources[].provider` | enum(mairui,user_import,user_input,system,exchange) | enum(mairui,user_import,user_input,system,exchange) | 一致 |
| `sources[].endpoint` | string / null | string / null | 一致 |
| `sources[].fetched_at` | string / null | string / null | 一致 |
| `security_code` | string | string | 一致 |
| `name` | string | string | 一致 |
| `items` | array | array | 一致 |
| `items[].trade_date` | 日期格式字符串 | string | 类型差异，见D5 |
| `items[].amount` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].main_net` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].super_large_net` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].large_net` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].medium_net` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].small_net` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].main_net_pct` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].is_final` | boolean | boolean | 一致 |

### announcements

| 字段路径 | B-03 | 真路由模型 | 结果 |
|---|---|---|---|
| `data_status` | enum(fresh,stale,pending,partial,unavailable) | enum(fresh,stale,pending,partial,unavailable) | 一致 |
| `data_as_of` | string / null | string / null | 一致 |
| `gaps` | array | array | 一致 |
| `gaps[].key` | string | string | 一致 |
| `gaps[].reason` | enum(no_source,not_yet_published,upstream_error,quota_deferred,user_input_missing,data_licence_unavailable,not_applicable) | enum(no_source,not_yet_published,upstream_error,quota_deferred,user_input_missing,data_licence_unavailable,not_applicable) | 一致 |
| `gaps[].message` | string | string | 一致 |
| `sources` | array | array | 一致 |
| `sources[].provider` | enum(mairui,user_import,user_input,system,exchange) | enum(mairui,user_import,user_input,system,exchange) | 一致 |
| `sources[].endpoint` | string / null | string / null | 一致 |
| `sources[].fetched_at` | string / null | string / null | 一致 |
| `items` | array | array | 一致 |
| `items[].id` | string | string | 一致 |
| `items[].published_at` | string | string | 一致 |
| `items[].title` | string | string | 一致 |
| `items[].category` | enum(periodic_report,other) | enum(periodic_report,other) | 一致 |
| `items[].category_raw` | string / null | string / null | 一致 |
| `items[].level_raw` | string / null | string / null | 一致 |
| `items[].url` | string / null | string / null | 一致 |
| `items[].url_host` | string / null | string / null | 一致 |
| `items[].file_format` | enum(pdf,html,other) / null | enum(pdf,html,other) / null | 一致 |
| `items[].first_seen_at` | string | string | 一致 |
| `next_cursor` | string / null | string / null | 一致 |
| `disclaimer` | Literal(固定免责全文) | Literal(固定免责全文) | 一致 |

### factors

| 字段路径 | B-03 | 真路由模型 | 结果 |
|---|---|---|---|
| `data_status` | enum(fresh,stale,pending,partial,unavailable) | enum(fresh,stale,pending,partial,unavailable) | 一致 |
| `data_as_of` | string / null | string / null | 一致 |
| `gaps` | array | array | 一致 |
| `gaps[].key` | string | string | 一致 |
| `gaps[].reason` | enum(no_source,not_yet_published,upstream_error,quota_deferred,user_input_missing,data_licence_unavailable,not_applicable) | enum(no_source,not_yet_published,upstream_error,quota_deferred,user_input_missing,data_licence_unavailable,not_applicable) | 一致 |
| `gaps[].message` | string | string | 一致 |
| `sources` | array | array | 一致 |
| `sources[].provider` | enum(mairui,user_import,user_input,system,exchange) | enum(mairui,user_import,user_input,system,exchange) | 一致 |
| `sources[].endpoint` | string / null | string / null | 一致 |
| `sources[].fetched_at` | string / null | string / null | 一致 |
| `security_code` | string | string | 一致 |
| `name` | string | string | 一致 |
| `trade_date` | 日期格式字符串 | string / null | 类型差异，见D5 |
| `factor_set_version` | string | string / null | 类型差异，见D5 |
| `counts` | object | object | 一致 |
| `counts.total` | integer | integer | 一致 |
| `counts.by_category` | map<string,integer> | map<string,integer> | 一致 |
| `items` | array | array | 一致 |
| `items[].factor_id` | string | string | 一致 |
| `items[].feature_key` | string / null | string / null | 一致 |
| `items[].name` | string | string | 一致 |
| `items[].category` | string | string | 一致 |
| `items[].value` | Decimal字符串 / null | Decimal字符串 / null | 一致 |
| `items[].unit` | string / null | string / null | 一致 |
| `items[].market_rank` | integer / null | integer / null | 一致 |
| `items[].market_rank_pct` | Decimal字符串 / null | Decimal字符串 / null | 一致 |

## 验证与证据

- 抽取/投影脚本与五份完整 JSON 证据存放在仓库外 `F:/workspace/team/status/`：`B-13-projection-audit.py`、`B-13-document-audit.py`、`B-13-{bars,financials,fund-flows,announcements,factors}-projection.json`。JSON 保留模式路径、原值与响应差异，只含既有纯合成夹具。
- 模型/ASGI 核对用既有 `B-05` 离线 venv，显式 `PYTHONPATH`，SQLite `:memory:` 与内存会话，无共享/生产库、Redis、真实麦蕊或证书操作；首次采集未修改冻结 worktree 源码，后续只有独立授权的 #63 安全返修改动，且已增量复核三场景投影。
- 权限负例复跑：只选五份既有 selfcheck 的 auth、owner 与 staging/production fixture 拒绝节点；共23项通过（bars 7，其余各4），证据为 `B-13-*-access.xml`。首次命令因 PowerShell 的 XML 参数拼接错误而未收集用例，纠正为独立参数后才得到本结果。本次未复跑五套完整测试、未跑全量/coverage。
- 重复抽取：按各资源冻结 worktree 指定 `PYTHONPATH=<root>/src/backend`、`UV_PROJECT_ENVIRONMENT=F:/workspace/team/venvs/B-05`，执行 `uv run --offline --no-sync --project <root>/src/backend python F:/workspace/team/status/B-13-projection-audit.py --resource <resource> --root <root> --output <全新证据路径>`。脚本拒绝覆盖既有输出。
- DeepSeek：复用 B-03 已逐项复核的 DeepSeek 夹具草稿；本单以确定性脚本抽取字段并人工核对，契约、权限和最终结论不外包。

申请新任务：请 Chief 将D2/D4保留为数据源接入后的覆盖项；B-06仍按既有门槛，r2正式执行归私聊唯一会话。
