# 评审 m 级问题统一修复（前端）

- 提交：`b23401a`（一个提交，只含 src/frontend/，22 个文件；本地提交，未 push）。基于 HEAD `687159f`（契约 v0.2.9）。
- 校验：typecheck 通过；eslint 0 警告；vitest 31 个文件共 459 例全部通过（新增 `review-9547181-m.test.tsx`、`review-53468a5-m.test.tsx`、`review-8249d6e-m.test.ts`，`t-f13.test.tsx` 新增/改写 3 例）。
- 干净检出跑 CI 步骤 rc=0：ignored-sources 错误 0（告警 4，与之前相同）；vitest 459/459；audit 1 个 moderate（原有）；check-dist 示例标记 0 命中，反向自检有效。
- 扫描：先 `rm -rf dist dist-mock`。secret_scan（工作区 200 个文件版本、暂存区 22 个）阻断 0、警告 0；gitleaks（工作区、暂存区）no leaks；禁用词与 11 位数字 0 命中。`git diff --cached --stat` 只含 src/frontend/，暂存区里没有非前端文件。
- 证书安全：没有输出、记录证书值或其指纹；新测试里的证书用随机字母现场生成。没有碰 MAIRUI_LICENCE。

## 9547181
| 编号 | 处理 |
|---|---|
| m1 mock `putLicence` 冷却规则 | `mocks/licenceStore.ts` 按后端 `licences/service.py set_licence` 实现：<br>- 同一证书重复 PUT，如果当前处于管理员暂停或冷却中（quota_exceeded / ip_limited，或 paused_until 晚于 mock 的 NOW），只更新元数据：状态不变，licence_id 不变，不重新验证。<br>- DELETE 时如果正在冷却，会记住冷却状态。之后重新 PUT 同一证书会恢复冷却状态；换一张证书则不恢复。<br>- 冷却已过期的，按新证书处理，重新验证。<br>- 管理员暂停优先于其他状态。 |
| m2 active 状态下的提示文案 | 202 提示改为按服务端返回的状态判断，不再用本地时钟：<br>- 只有在冷却中（quota_exceeded / ip_limited / paused_until 有值）才提示“冷却到期前不会重新验证”；<br>- 其余情况显示“证书已加密保存，之后不会再显示。当前状态“X”。” |
| m3 PUT / PATCH 遇到 503 | 补了界面用例（两者都显示维护提示）和接口顺序用例：PUT 先 400 后 503；PATCH 先 503 后 409。mock 判定顺序也对齐：PUT 为校验 → 503 → 限速；PATCH 为校验 → 503 → 409。 |
| m4（顺带） | mock `/test` 的判定顺序对齐后端：503 → 暂停 409 → 未设置 409 → 限速 → INGEST_PAUSED 503。 |
| m5 过期后显示“剩 -N 天” | 新增 `expiryLeftText`：过期显示“已过期”，当天显示“今天到期”，其余显示“剩 N 天”。设置页、/admin/ingest、/admin/data-licences 三处已统一使用，并有用例覆盖。 |

## 53468a5
| 编号 | 处理 |
|---|---|
| m1 Idempotency-Key 不轮换 | `useCreatePlanDraft` 的换 key 规则：<br>- `signal_ids` 变化时换新 key；<br>- 出现非网络错误（非 NETWORK_ERROR）时换新 key，规则与确认接口一致；<br>- 网络错误时保留原 key，方便重试。<br>用例：409 后重试时 key 不同；网络错误后重试时 key 相同。 |
| m2 自述第 3 条 | 已更正 `T-F18.md` 第 3 条：契约 §7.7 已写明 stale、expired 都可以重新生成，“原草案保持不变，两者之间不建关联”。原文用删除线保留。第 7 条标注为已由 P18 处理。 |

## 8249d6e
| 编号 | 处理 |
|---|---|
| m1 | 85e9b70 已处理（没有校正过的服务端时间时不传 `form_started_at`，`isServerClockCalibrated`）。本次复核仍然有效。 |
| m2 mock 判定顺序 | mock 注册改为按 §7.1 的顺序判定：<br>1. 注册模式（closed → 503，不计数）；<br>2. IP 限速：每次尝试都计数，校验失败和蜜罐命中也计，5 次/小时，与后端默认 `register_ip_per_hour` 一致；超出返回 429 和 Retry-After；<br>3. 400；<br>4. 409；<br>5. 待审核数上限：`pending_cap` 默认 200，超出返回 503 REGISTRATION_CLOSED，与关闭注册同码；<br>6. 蜜罐。<br>用例：蜜罐命中 5 次后第 6 次返回 429；校验失败也计数；关闭注册时不计数；待审核数上限先于蜜罐、晚于 409。 |
| m3 `website` 不是字符串 | 契约 §7.1 规定类型为 `string \| null`，且“不校验内容与长度”；后端 HEAD 的 `RegisterIn.website: str \| None` 遇到数字会返回 400。mock 已对齐：不是字符串也不是 null 时返回 400 `{field:"website", issue:"invalid"}`；null 视为未填；超长字符串照常按命中处理；全是空白不算命中。界面不会发出非字符串，所以对用户可见的行为没有变化。 |
| m4 | 85e9b70 已经补了 `/plans/:id` 占位页，53468a5 的确认跳转可以落地。 |

## 7afbc06
| 编号 | 处理 |
|---|---|
| m1 | 点“上一期”时，如果需要先加载下一页，加载完成后直接跳到新一页的第一项，点一次就到。原用例改为“点一次就跳转”。 |
| m2 | 切换日期（上一期、下一期、下拉选择）时保留当前的查询参数，`?filter=` 不会丢失。新增用例。 |
| m3 | StockCard 改用 `aria-labelledby` 指向标题（证券名称和代码），不再用 aria-label 覆盖整张卡。EvidenceChips 的证据标签可以用 Tab 聚焦（tabIndex=0，带 aria-label），聚焦时显示详情（Tooltip 的 trigger 为 hover + focus），在标签上按 Enter 或空格不会触发外层卡片跳转。加了 focus-visible 样式。新增用例。 |
| m4 | 同 8249d6e m4，已处理。 |
| m5 | `src/test/setup.ts` 中把 `configure({asyncUtilTimeout: 5000})` 统一放宽；`vite.config.ts` 中 `testTimeout: 20000`。t-f03、t-f08、t-f13、t-a09 不再需要逐个改超时。没有限制并发。 |

## T-A10 待定项：本次采纳了哪些
只采纳了“已有答案或已写明不改”、且不依赖 v0.2.9 新内容的项：
- **P18 已采纳**：409 `INVALID_STATE_TRANSITION` 按 `details.from` 显示不同文案（新增 `lib/stateTransition.ts`）。
  - 信号：已确认 → “该信号已被确认为计划”；已过期、已失效、已被取代 → “信号已失效（…）”；已忽略 → “该信号已忽略”；其他状态 → “该信号当前为“X”，不能进行此操作”。
  - 草案：已确认、已放弃，以及其他状态，各有对应文案。
  - `from` 未知或缺失时回落到通用文案。
  - 已接入草案详情页（重新生成、确认、放弃）和候选信号详情页（拟定、忽略）。
  - mock 的 409 按 §6.0 补上 `details: {from, to, allowed}`。
- **P14 已采纳**：重新生成草案时如果原信号已失效，显示“信号已失效（…），不能重新生成草案”。T-F18 自述已同步更正。
- **已符合，无需改动**：P16（策略名经来源信号取得）、P19（只有 pending 能放弃）、P20（`form_started_at` 可不传）、P21（即本次修复的内容）。P04、P05、P06 已在 d26e1d3 中完成。
- **留到 v0.2.9 统一同步（本次没有做，也没有猜）**：P01、P02（持仓行可空性，`security_type`/`estimated`）、P03、P07（events 分页 `{items}` 和 cause 枚举，不兼容）、P08、P09（原因加 `security_code`/`name`）、P10、P11（跟踪统计范围）、P12、P13（多信号合并、整手规则的校验）、P15（discard 请求体改为 `{}`，不兼容）、P17（依赖计划接口）、`/non-executable-reasons` 默认改为 status=active（不兼容）、`CONTRACT_VERSION` 改为 v0.2.9。

## 需要谁做什么
- **编排者**：契约 v0.2.9（`687159f`）已经落地，其中有三项不兼容改动（events 分页、discard 请求体、原因列表默认只返回 active），前端目前仍按 v0.2.8。需要单独安排“前端同步 v0.2.9”的任务。
- **评审**：评审 `b23401a`。
- **后端**：无。

## 他人改动
- 工作区中他人未提交的后端改动，本次没有碰，也没有暂存：
  - 修改：src/backend/app/api/v1/__init__.py、cli/delete_user_data.py、config.py、db/tables/accounts.py、marketdata/security_types.py、pyproject.toml、uv.lock。
  - 未跟踪：api/v1/{accounts,imports,portfolio,trades}.py、common/idempotency.py、domain/portfolio.py、importing/*（decoding、findings、keys、masking、parsers/、pipeline、preview、storage、text）、migrations/versions/0014_t_b46_imports_trades.py。
  - 与上轮相比，新增了 api/v1/__init__.py 的修改，以及 imports.py、portfolio.py、trades.py、importing/text.py。
- 本任务期间新增的他人提交：f72b8c7（后端：注册关闭时先于解析请求体返回 503）、687159f（契约 v0.2.9）。
