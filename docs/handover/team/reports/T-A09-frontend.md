# T-A09 前端同步（契约 v0.2.8 + 67d123a 补充裁定 + 编排者 Q63）

- 提交：`9547181`（只含 src/frontend/，本地提交，未 push）
- 校验：typecheck / eslint 0 警告 / vitest 25 文件 377 例全过；干净检出（/tmp/wt-verify）跑 CI 步骤 rc=0（audit 1 moderate，同前）；check-dist 0 命中；secret_scan、gitleaks（工作区与暂存）0 命中；禁用词与 11 位数字扫描 0 命中。
- 截图（1440×900 深色，示例数据，无外部请求、无控制台错误）：`/workspace/team/reports/T-A09/`
  - 01-etf-stock-page.png：ETF 个股页
  - 02-portfolio-convertible.png：持仓含可转债
  - 03-licence-paused.png：证书被管理员暂停，测试按钮禁用
  - 04-admin-ingest.png：管理端按证书采集表

## 已完成（按 v0.2.8 清单）

| # | 内容 | 前端处理 |
|---|---|---|
| — | 版本 | `CONTRACT_VERSION='v0.2.8'`；示例横幅、mock 注释同步 |
| 3 | security_type 加 etf | 枚举加 `etf`，类型徽标“ETF”（个股页头、搜索结果） |
| 4 | 搜索默认含 ETF | 前端未传 `types`，自动获得默认值；结果中非股票显示类型徽标；mock 默认 `stock,cdr,etf`，排序 stock > cdr > etf > index |
| 5 | ETF 资料空字段 | 资料面板加“类型”行；ETF 的行业/概念/股本显示“不适用”，加“交易单位：每手 100 份，价格保留 3 位小数” |
| 6/7 | not_applicable | gap_reason 加 `not_applicable`（“不适用”）；财务/资金流/因子/公告在所有缺口均为 not_applicable 时显示“不适用：该证券类型没有此类数据”，不显示错误或空表；数据状态标签显示“不适用” |
| 8 | ETF 价格 3 位小数 | 个股页现价与涨跌额按 3 位小数；mock ETF 行情、K 线为 3 位小数 |
| 10 / 17② | INSTANCE_SCOPE_INVALID | 按 `details.issue` 给出文案：`security_type_not_supported`（etf）→“ETF 暂不支持建策略实例”；`unknown_security` →“证券代码不存在”。个股页目前没有“建策略实例”按钮，无需隐藏 |
| 12/13 | 暂停期 / 重复 PUT 返回 202 | 保存成功提示按返回状态区分：暂停中“管理员恢复后才会验证”；冷却中“当前状态…，冷却到期前不会重新验证” |
| 14 | 暂停期禁用测试 | `paused_by_admin` 时“测试证书”禁用（带提示）并显示说明；mock 测试接口返回 409 `DATA_LICENCE_UNAVAILABLE{status:"paused_by_admin"}` |
| 17③ | 设置开关关闭 | PUT/PATCH/test 返回 503 MAINTENANCE 后显示“设置暂未开放”，禁用保存与测试，删除仍可用，不再显示通用错误框 |
| 1 | /admin/ingest 按证书 | 新页面 `/admin/ingest`（管理员菜单“采集状态（管理）”）：顶部合计（主实例、近 1 分钟调用、队列、24 小时错误、新鲜度），下表每张证书一行（状态、档位、到期/剩余天数、今日调用/日额度、近 1 分钟/上限、P0/P1/P2、熔断至、最近错误），按服务端顺序显示；`licences_truncated` 时提示“只显示前 500 张”。非管理员 404 |
| 15 | 管理端类型手写 | `api/adminTypes.ts` 按契约 §5.1/§7.9 手写，不从 openapi 生成 |
| 16 | 首页 /today | 已是 `/` → `/today`（之前已实现） |
| 17① | ETF 整手 | 导入码 46 说明已含“ETF 按 100 份整数倍”（之前已实现） |
| Q63 | 可转债持仓 | 名称后显示“可转债·无行情”；现价、市值、浮动盈亏、盈亏% 显示“—”；仓位% 加“估算”标；含可转债时总资产标“估算”并加一行说明；代码不链接到个股页。持仓表新增“现价”列（市值/数量，3 位小数） |

mock 补充（只在 MSW）：ETF 示例 `510300.SH 示例沪深300ETF`；可转债示例持仓 `113050.SH 示例转债`（按成本估市值、盈亏 0）；证书 `licence_id`；管理员暂停按用户记录（DELETE 后 PUT 不解除）；`setMockLicenceSettingsEnabled(false)` 模拟设置关闭；新增示例账号 `paused_user`（证书被管理员暂停）；`disabled_user` 证书为管理员暂停、`locked_user` 为额度用完，供管理端表演示。

测试：`src/pages/t-a09.test.tsx`（14 例）：版本；搜索默认含 ETF 与排序；ETF 页头/资料/四个页签“不适用”；422 文案；暂停禁用测试与 409；暂停期 PUT 202；503 → 设置暂未开放；管理端 404、按证书排序、无全站 licence 键；可转债识别与显示；无可转债时不标估算。

## 遗留问题（未改契约，需架构师 / 编排者定）

1. **U3 与 Q63 不一致**：契约 U3 默认仍写“本版不变：按原代码显示，无行情”，编排者 2026-11-02 已裁定显示“可转债·无行情”、现价与市值“—”、仓位“估算”。前端按编排者裁定实现；请架构师在契约中同步 U3（以及后端对可转债行 `market_value`/`weight_pct` 的口径：mock 假设按成本估算、`pnl=0`）。
2. **持仓没有证券类型字段**：`PortfolioPosition` 无 `security_type`，前端只能按代码前缀识别可转债（沪 110/111/113/118，深 123/127/128，见 `lib/securityKind.ts`）。建议契约给持仓行加 `security_type`（或 `quote_available: boolean`），前端随即改为读字段。
3. **ETF 成交量单位**：行情 `volume` 前端统一按“手”显示（÷100）；ETF 每手 100 份，数值上一致，但文案是“手”而非“份”。是否需要改为“份”请架构师确认。
4. **#2 AdminDataLicence.licence_id**：前端目前没有 `/admin/data-licences` 页面（只有用户审核与本次采集状态页），未做两页互跳（契约标“可选”）。
5. **截断提示链接**：`licences_truncated` 时只用文字提示“完整列表见 /admin/data-licences”，因该页未实现，没有做链接。
6. **管理员暂停 UI**：补充裁定⑤只定义了幂等，前端没有管理员暂停/恢复按钮（契约未要求）。

## 需要谁做什么

- 运维：push `9547181`（连同前面各项提交）。
- 架构师：处理上面遗留 1–3（U3 文字、持仓类型字段、ETF 数量单位）。
- 无需后端配合前端改动；后端实现 `/admin/ingest/status` 新结构后，前端无需再改。
