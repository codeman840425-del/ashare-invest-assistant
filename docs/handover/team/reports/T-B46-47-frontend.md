# T-B46 / T-B47 前端同步（v0.2.9）

- 依据：`reports/T-B46-47-rulings.md`（第 150 行起“前端待办”）、docs 提交 4532478 / 07b8d74（契约 #27、§7.2 /portfolio、§7.3 周期评估、§7.9 /admin/ingest/status）
- 提交：`5969886`（只含 src/frontend/，15 个文件，+389 / −54；本地提交，未 push）
- 时间：北京时间 2026-11-02 09:48 提交

## 结果

| 项 | 做了什么 |
|---|---|
| 1 持仓按 `security_type` 判断（R6） | 删除 `lib/securityKind.ts`（不再看代码前缀）。`security_type=null` → “不在主数据·估算”，代码不可点；在主数据中但 `estimated=true`（问题 79：无日线收盘价也无快照参考价）→ 只标“估算”，可进个股页；两种都显示现价/市值/盈亏“—”、仓位标估算、总资产标估算。说明文字按两种原因分开写。非股票类型（etf/cdr/index）按 `SECURITY_TYPE` 显示类型标签。 |
| 2 采集状态页显示 `alerts[]`（R10） | 新增“告警（n）”卡片，置顶：级别标签 + 服务端 `message` 原样 + `key`；保持服务端顺序；空数组显示“当前无告警”。类型：`alerts: IngestAlert[]`（不为 null）、`egress_ip_masked: string|null`、freshness 6 个 dataset 固定顺序、状态不含 partial。leader 为 null 显示“无（没有未过期的租约）”。 |
| 3 周期评估“数据不足”（R8/R9） | 个股页与候选信号卡：适合周期为空且有 `data_missing` 封顶 → 显示“数据不足”；各周期不适合且有该周期 `data_missing` 封顶 → 行内标“数据不足”。界面不出现“都不适合”。候选信号卡头部：适合周期为空且没有 data_missing 封顶 → “—”。 |
| mock | `/admin/ingest/status` 按 §7.9 口径生成示例告警（`mocks/ingestAlerts.ts`，阈值取 plan `admin_alerts` 初值，文案标“（示例）”）；freshness 改为 6 个 dataset（financials 示例为 stale）；`ip_limit_alerts_24h` 示例改为 1；其他账户 /portfolio 带 `cash` gap（`user_input_missing`）；新增 `allDataMissingAssessment()`（T-B30a 前的全 data_missing 示例，仅测试/覆盖用）。 |
| 测试 | 新增 `pages/t-b46-47.test.tsx`（13 条）；更新 t-a09、t-a10（去掉前缀判断用例，改断言 est-label / est-note / est-weight）。 |

## 校验

**工作区**（/workspace/ashare-invest-assistant/src/frontend）
- typecheck、eslint `--max-warnings=0` 通过；vitest 36 个文件 / 543 条全部通过
- 提交前扫描（先 `rm -rf dist dist-mock`）：secret_scan files 0 阻断 0 警告；gitleaks dir（仓库配置 + 默认规则）均 no leaks；暂存区 gitleaks no leaks；secret_scan staged 0 / 0；禁用词与 11 位数字 0 命中
- `git diff --cached --stat`：只含 src/frontend/

**干净检出**（git worktree，HEAD=5969886，`/tmp/cleanci-c5.log`）
- rc=0；ignored-sources 错误 0 告警 4（与之前相同）；eslint、typecheck 通过；vitest 36 / 543 通过；pnpm audit high 以上 0（1 moderate，与之前相同）；build 后 check:dist 示例标记 0 命中、代码块 ≤ 500 kB；dist-mock 反向自检有效

**截图**：`/workspace/team/reports/T-B46-47-frontend/01-admin-ingest-alerts.png`（1440×900 深色，管理员，示例数据）；console 错误 0、页面错误 0、外部请求 0（`result.json`）。

## 待定（契约/裁定写得不清，前端未猜，先按下列最保守做法实现）

1. **R6 契约内矛盾**：§7.2 U3 一句“其他行 estimated=false”与裁定 ②（在主数据但无价格时也 estimated=true）矛盾；前端只看行上的 `estimated`，两种都能显示。另：有 non-null 估算行时 `data_status` 是否要降为 partial 未写明。→ 架构师
2. 在主数据中的估算行，问题 79 只写标“估算”；是否需要更具体的标注（如“无收盘价·估算”）待定。
3. **alerts 文案**：契约只说 `message` 为“固定中文文案”，未给原文。前端原样显示服务端文案；mock 文案均为示例。→ 后端按 §7.9 实现并给出文案清单，架构师写进契约。
4. alerts 级别的显示文字“严重 / 警告”契约未给；排序未规定（前端保持服务端顺序）。
5. 证书 14 天内到期的告警 key 未规定：mock 暂用 `licence.<status>`（截图里是 `licence.active`），是否应为 `licence.expiring` 之类待定；同一 key 是一条还是按证书多条也未写明（mock 按 key 去重）。
6. heartbeat 告警没有 mock（状态接口里没有心跳时间字段可推算）。
7. “数据不足”的精确判定未写明：前端取“适合周期为空且存在 data_missing 封顶”（整体）与“该周期不适合且有该周期 data_missing 封顶”（逐周期）；gate 封顶不算。→ 架构师确认
8. freshness 的 dataset 名称契约未给中文名，前端原样显示 key。
9. 默认 mock 的周期评估仍保留示例分布（有适合周期）；T-B30a 前全 data_missing 的情形用测试覆盖（`server.use`），没有改默认 mock。

## 需要谁做什么

- **后端**：§7.9 `alerts[]` 实现与固定中文文案（含 14 天到期告警的 key）；/portfolio 按 R6 输出 `security_type` 与行级 `estimated`。
- **架构师**：澄清上面 1、3、4、5、7（改契约原文，前端随后对齐）。
- **运维 / 用户**：问题 78 告警阈值在 T003 实测后复核（目前 mock 用 plan 初值 60/300/3600 秒、0.9、1、20、14 天）。

## 其他人的未提交改动（未 add，未改动）

deploy/compose/docker-compose.yml、deploy/docker/secret-env.sh、deploy/runbooks/database.md、deploy/scripts/compose.sh、scripts/ci/check_secret_boundary.py、scripts/ci/tests/test_secret_boundary.py（修改）；deploy/scripts/app-master-key-ensure.sh、scripts/ci/tests/test_app_master_key_ensure.py（未跟踪）。
另：我提交后 21 秒有人提交了 be8d13a（docs/strategies，T-R11 feature_spec.md），当前 HEAD 是它；干净检出验证的是 5969886。
