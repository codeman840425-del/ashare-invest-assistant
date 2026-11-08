# 评审 b23401a：前端合并修复各轮评审的 m 级问题

- 评审人：架构师（只读评审，没有改代码，也没有提交）
- 评审对象：`b23401a`（只改了 `src/frontend/` 下的 22 个文件）。修复说明见 `review-m-fixes-frontend.md`
- 依据：契约 `docs/api-contract.md` v0.2.9；原评审报告 review-9547181、review-53468a5、review-8249d6e、review-7afbc06、T-A10-pending（只看 P14、P18）、review-d26e1d3
- 日期：2026-11-02（Asia/Shanghai）

## 一、结论：**有条件通过**

各轮评审的 m 级问题都已修复，或者之前已经处理。没有发现 B 级或 M 级问题。mock 的判定顺序、冷却规则与契约和后端实现一致。测试环境只加了两处超时设置，没有放宽断言，也没有放宽网络隔离。另外我把这两处设置在 /tmp 副本里还原后重跑，测试全部通过，说明这次的测试结果不依赖这两处放宽。

“有条件”指以下两点：
1. d26e1d3 的 m2（高亮行不在已加载的行里）和 m3（mock 没有对暂停/恢复理由去空白）**未包含**在本提交中，需要补上。
2. 本次新发现 8 条 m 级问题（见第五节），可以在下一次前端提交里一起改，不阻塞合并。

## 二、干净检出验证

用 `git archive b23401a` 导出到 `/tmp/review-b23401a`，在 `src/frontend` 下按顺序（没有并行）执行：

| 步骤 | 命令 | 结果 |
|---|---|---|
| 安装 | `pnpm install --frozen-lockfile` | rc=0 |
| 类型检查 | `pnpm run typecheck`（三个 tsconfig） | rc=0 |
| lint | `pnpm exec eslint . --max-warnings=0` | rc=0，0 警告 |
| 测试 | `pnpm run test`（vitest run） | rc=0；31 个文件中 30 个通过、1 个跳过；459 例中 458 例通过、1 例跳过，用时 21.5 秒 |
| 对照组 | 复制到 `/tmp/review-b23401a-strict`，**还原** `asyncUtilTimeout: 5000` 和 `testTimeout: 20_000` 后重跑 vitest | 458 例通过、1 例跳过，用时 21.7 秒 |

跳过的 1 例是 `tracked-sources.test.ts`（B1 守卫）。它需要 `.git` 目录，导出目录里没有，所以跳过是预期行为。修复说明里写的“459/459”是在带 `.git` 的工作区里跑的；干净检出里实际是 458 例通过加 1 例跳过。这不算问题，但以后报告里最好分开写。

## 三、原各轮 m 级问题逐条核对

| 来源 | 条目 | 结果 | 说明 |
|---|---|---|---|
| 9547181 | m1 同一证书重新提交（HMAC 相同）不重置冷却 | 已修复 | `licenceStore.putLicence`：摘要相同，且证书被暂停或仍在冷却（`keepsState`）时，只更新元数据，保留 `licence_id`；被暂停的仍是 `paused_by_admin`。与后端 `licences/service.py set_licence` 一致 |
| 9547181 | m2 DELETE 后重新提交仍要沿用冷却 | 已修复 | `deleteLicence` 在 active、quota_exceeded、ip_limited 且仍在冷却时记录冷却，下次 PUT 用 `takeCooldown` 取回。与后端 `_remember_cooldown` 和 `_take_cooldown` 一致 |
| 9547181 | m3 设置页“冷却到期前不会重新验证”在任何状态下都显示 | 已修复 | 改为只在 `inCooldown` 时显示，其他状态显示“当前状态 X” |
| 9547181 | m4 mock 的 503/409/限速判定顺序 | 已修复 | PUT：400 → 503 → 限速；/test：503 → 暂停 409 → 未设置 409 → 限速 → INGEST_PAUSED。与后端 `api/v1/data_licence.py` 一致 |
| 9547181 | m5 过期证书显示“剩 -N 天” | 已修复 | 新增 `expiryLeftText`：小于 0 显示“已过期”，等于 0 显示“今天到期”，三个页面都已改用。原评审建议写“已过期 N 天”，现在不显示天数，可以接受 |
| 53468a5 | m1 生成草案的 Idempotency-Key 在服务端给出明确错误后不换 | 已修复 | `useCreatePlanDraft`：`signal_ids` 变了换键；成功后换键；除 `NETWORK_ERROR` 外的 ApiError 也换键；网络错误重试时沿用原键。与 `useConfirmPlanDraft` 一致，有测试覆盖 |
| 53468a5 | m2 T-F18 自述第 3 条不准确 | 已修复 | `/workspace/team/reports/T-F18.md` 第 3 条已更正并引用 §7.7；第 7 条标为“已处理（P18）” |
| 8249d6e | m1 | 之前已处理 | 在 85e9b70 中处理 |
| 8249d6e | m2 mock 注册缺少 IP 限速和待审核数上限 | 已修复 | 顺序是关闭注册 → IP 限速（每小时 5 次，每次尝试都计，Retry-After）→ 400 → 409 → 待审核数上限 503 REGISTRATION_CLOSED → 蜜罐，与 §7.1 和后端 `auth.py register` 一致 |
| 8249d6e | m3 `website` 不是字符串时的处理 | 已修复 | 非字符串返回 400 `{field:"website", issue:"invalid"}`；null 视为未填 |
| 8249d6e | m4 | 之前已处理 | — |
| 7afbc06 | m1 日报切换日期时丢失查询参数 | 已修复 | `go(d)` 保留 `search` |
| 7afbc06 | m2 “上一期”到已加载数据的末尾时不能继续 | 已修复 | `loadOlder` 等待 `fetchNextPage` 完成后跳到下一期（但见第五节 N6） |
| 7afbc06 | m3 卡片 aria-label 覆盖了内部内容 | 已修复 | 改用 `aria-labelledby` 指向标题，并增加证据 chip 的键盘聚焦（但见第五节 N2–N5） |
| 7afbc06 | m4 | 之前已处理 | — |
| 7afbc06 | m5 测试在负载高时超时 | 已按原建议实现 | 见第四节 |
| T-A10 | P14 重新生成草案在原信号失效时的文案 | 已修复 | `transitionText(..., {regen:true})` 显示“信号已失效（…），不能重新生成草案” |
| T-A10 | P18 409 INVALID_STATE_TRANSITION 按 `details.from` 区分文案 | 已修复 | 新增 `lib/stateTransition.ts`，草案页和信号页都已接入；mock 的 409 `details` 带上了 `{from, to, allowed}` |

## 四、d26e1d3 的条目是否包含

| 条目 | 是否包含 | 说明 |
|---|---|---|
| m1 过期证书显示“剩 -N 天” | **已包含** | 与 9547181 m5 是同一处修复（`expiryLeftText`），三个页面都已改 |
| m2 从其他页面跳转过来时，目标行不在前 50 行就不高亮 | **未包含** | `AdminDataLicencesPage.tsx:55,148` 中 `?user=` 只用于 `rowClassName`。目标行没加载时，页面既不会自动加载更多，也没有任何提示 |
| m3 mock 没有对暂停/恢复理由去空白 | **未包含** | `accountHandlers.ts:280` 仍直接用 `reason.length` 校验，只有空白的理由会被当作合法。契约 #997 只写了 `string(1–200)`，后端会先去空白再校验，mock 应与后端一致 |
| 本地筛选 | 符合契约，不需要改 | 契约 v0.2.9 #26②：`/admin/data-licences` 在 V1 没有服务端筛选，由前端只筛已加载的行。页面已提示“只筛选已加载的 N 行（接口未提供筛选参数）” |

## 五、测试环境改动评估（setup.ts / vite.config.ts）

- `src/test/setup.ts`：只加了 `configure({ asyncUtilTimeout: 5000 })`。`server.listen({ onUnhandledFrame: 'error' })` 没有改，网络隔离没有放宽，也没有改任何断言。
- `vite.config.ts`：只加了 `testTimeout: 20_000`。
- 判断：**不是为了让测试通过而放宽测试环境**。还原这两处后测试照样全部通过（见第二节对照组），说明当前没有哪个测试依赖这两处放宽。但这两处是全局设置：`findBy*` 的等待时间变成原来的 5 倍，单个测试超时变成原来的 4 倍。这会掩盖变慢的情况，测试卡住时也要等更久才失败。已列为 N8。

## 六、契约一致性

- 409 `INVALID_STATE_TRANSITION`：`details` 带上了 `{from, to, allowed}`，符合 §4。草案进入终态后返回 `allowed: []`，符合要求。信号的 `allowed` 有一处不准确，见 N7。
- 幂等：符合 §2 “同键同体返回首次结果，同键异体返回 409”。
- 数据许可证冷却和判定顺序：与契约 #13 及其补充、后端实现一致。
- 注册：与 §7.1 一致。mock 只模拟了每小时的限速窗口，没有模拟每日窗口，这在 mock 里可以接受。
- 以下内容在 b23401a 之后（HEAD 439746e）才进入契约 v0.2.9，不在本次评审范围内。前端需要另行同步：
  - #26①：恢复（resume）幂等，返回 204；
  - #26⑤：暂停/恢复发通知；
  - 候选信号 events 改为分页 `{items}`；
  - discard 的请求体；
  - `/non-executable-reasons` 默认 `status=active`；
  - `CONTRACT_VERSION`。

## 七、新发现的问题

没有 B 级和 M 级问题。

| 编号 | 级别 | 位置 | 问题 | 建议 |
|---|---|---|---|---|
| N1 | m | `lib/stateTransition.ts:17,24` | 用 `from in SIGNAL_STATE` / `from in PLAN_DRAFT_STATUS` 判断，原型链上的键也会命中（例如 `from="toString"`），会进入分支并拼出错误文案，而不是回落到 null（通用文案） | 改用 `Object.hasOwn(...)` |
| N2 | m | `components/EvidenceChips.tsx:28` | `aria-label` 放在没有 role 的 `span` 上。按 ARIA 规范，generic 元素不允许设置 `aria-label`，读屏软件可能忽略 | 加 `role="button"`（它会触发 Tooltip），或者把说明放进可见文字或 `aria-describedby` |
| N3 | m | `EvidenceChips.tsx:29` | 按空格时只调用了 `stopPropagation`，没有调用 `preventDefault`，焦点在 chip 上时按空格会滚动页面 | 对空格键也调用 `preventDefault()` |
| N4 | m | `DailyReportPage.tsx:88` 与 EvidenceChips | `tabIndex=0` 的 chip 嵌套在 `role="link"` 的卡片里。可交互元素互相嵌套，读屏软件的行为不一致 | 把 chip 移到 link 区域外面，或者改成卡片内有一个独立的“查看”链接 |
| N5 | m | `DailyReportPage.tsx:88-91` | 卡片的可访问名称只剩“名称 + 代码”，丢掉了原来的“候选信号卡”语义，读屏用户不知道点下去会去哪里 | 用 `aria-labelledby` 再拼一个隐藏的说明节点，或者用 `aria-describedby` |
| N6 | m | `DailyReportPage.tsx:49-50` | `loadOlder` 在 `await fetchNextPage()` 之后无条件 `navigate`。如果用户在等待期间已经切换了日期或离开了页面，会被拉回去 | `await` 之后检查当前日期是否还是发起请求时的日期，或者检查组件是否已卸载 |
| N7 | m | `mocks/signalHandlers.ts` 中的 `signalAllowed` | `blocked` 信号返回的 `allowed` 是 `['dismissed']`。按 §6.0，blocked 可以通过手动解除原因变成 released，按 §4 的定义应该是 `['released','dismissed']` | 按枚举顺序改为 `['released','dismissed']`，或者在契约里写明手动解除不算“通过接口可达” |
| N8 | m | `test/setup.ts`、`vite.config.ts` | 超时放宽是全局的（见第五节）。还原后测试照样通过，说明现在并不需要 | 还原成默认值，只在确实慢的个别用例上单独设置超时；或者只在 CI 用环境变量调高 |

其他观察（不算问题）：
- 生成草案在 5xx 错误后也会换键，与确认的做法一致。但如果是 504，服务端可能已经提交成功，换键后重试有可能生成第二份草案。建议在后续的契约里统一写明 5xx 时是否沿用原键。
- 后端的请求体类型错误（Pydantic 422 转 400）发生在限速之前，所以不计入限速次数。mock 把 `website: 1` 这类错误也计入限速次数。这只是计数上的小差异，不影响页面行为，可以不改。
- 在浏览器 mock 模式下，注册超过 5 次会返回 429，刷新页面后重置。这符合预期，但最好在 mock 的说明里写一句。

## 八、谁需要做什么

| 负责人 | 事项 |
|---|---|
| 前端 | 补上 d26e1d3 的 m2（目标行没加载时，自动加载更多直到找到该行，或者显示“该用户不在已加载的行里”并提供加载入口）和 m3（mock 先对理由去空白，再按 1–200 字校验，并补测试）。同一次提交里一起修 N1–N8。N8 建议还原全局超时设置 |
| 前端 | 以后的修复说明把“带 .git 的工作区”和“干净检出”两种测试结果分开写 |
| 编排者 | 安排前端同步契约 v0.2.9 在 b23401a 之后新增的内容（见第六节最后一条），并在下次评审时一起核对 |
| 后端 | 本提交不涉及后端 |
