# 评审报告：8249d6e（T-F24 邀请码注册页与蜜罐字段）

- 评审人：架构师（代审）
- 日期：2026-11-02
- 评审依据：契约 v0.2.8 §7.1 `POST /auth/register`（蜜罐与最短填写时间）、变更表 #11、§9 测试第 10 条；自述 `reports/T-F24.md`
- 评审方式：只读。没有改代码，也没有提交。`git archive 8249d6e src/frontend docs` 导出到 `/tmp/rv-8249d6e`，在导出目录做干净检出后跑全部脚本。

## 0. 干净检出

| 项目 | 结果 |
|---|---|
| 提交所在位置 | 在本地 main 上（父提交 116cb7e，子提交 307132b） |
| 改动范围 | 只改 `src/frontend`，共 10 个文件，+379 / −13 |
| `pnpm install --frozen-lockfile` | 通过 |
| typecheck（3 个 tsconfig） | 通过 |
| `eslint . --max-warnings=0` | 通过，0 警告 |
| test | 20 个文件通过，1 个跳过；335 个用例通过，1 个跳过（`tracked-sources` 在没有 .git 时跳过，已用 `git check-ignore --no-index` 补查，没有被忽略的已跟踪文件） |
| build | 通过 |
| check:dist | 通过：33 个文件，20 个示例标记 0 命中，各代码块都不超过 500 kB |
| 证书安全 | diff 中没有证书值或疑似子串，也没有口令或密钥。截图脚本只连 <host>，并记录外部请求 |
| 作废内容 | consent、risk_assessment、fit_ack、`kind: requires`、/onboarding、me/export、数据导出、PROFILE_OR_CONSENT 均 0 命中 |

说明：第一次把两个提交的测试同时并行跑，因为机器负载高，出现 2 个超时失败：t-f03 的 `stock-head` 和 t-f22a 的 `licence-page`，都是原有用例，与本提交无关。改成依次单独跑后全绿。另外对 t-f24 连续单独跑了 3 次，每次都是全绿。

## 1. 结论

**通过。** 没有 B 级问题，也没有 M 级问题，只有 4 条 m 级问题。蜜罐的隐藏方式、时钟校正、mock 的判定逻辑都与契约 v0.2.8 #11 一致。

## 2. 重点核对

| 检查项 | 结论 | 说明 |
|---|---|---|
| `website` 隐藏 | ✅ | 外层 `.reg-hp` 用 `position:absolute; left:-10000px; 1×1; overflow:hidden` 移出可视区，没有用 display:none，这样能骗过只跳过 display:none 输入框的机器人。外层加了 `aria-hidden="true"`。没有用 Form.Item，所以不进表单校验，也不在可访问的表单控件里 |
| tabindex=-1、autocomplete=off | ✅ | `<input name="website" tabIndex={-1} autoComplete="off">`，有测试断言 |
| `form_started_at` 的计算 | ✅ | 由 `RegisterForm` 首次渲染时的 `useState(() => serverNowMs())` 给出，出错后重试沿用同一个值。`serverNowMs = Date.now() + offset`，其中 offset = `Date` 头 − 本地收到响应的时刻。因为 `Date` 头只到秒且早于收到时刻，算出的 offset 不会大于真实偏差，所以 `form_started_at` 只会偏早，不会把真人误判为“太快”。推导见下方 |
| 校正时机 | ✅ | 只有 `/meta/registration` 成功后才渲染表单，所以取值总在校正之后。`onResponse` 在处理 304 之前调用，ETag 返回 304 时也会校正。API 是同源的 `/api/v1`，`Date` 头可以读到（跨域时不在 CORS 白名单里，但本项目不跨域） |
| 不让真实用户误触 | ✅（有 1 条 m） | 键盘按 Tab 到不了，读屏器读不到，浏览器不会自动填充；邀请制下邀请码和申请说明都必填，3 秒内填完不现实。只有在 `Date` 头缺失时会回退到本地时钟，见 m1 |
| 错误码处理 | ✅ | 503 REGISTRATION_CLOSED 显示关闭页；409 显示在用户名下；400 VALIDATION_ERROR 按字段显示，其中 `invite_code invalid` 显示为“邀请码无效或已失效”；不属于表单字段的错误（如 `form_started_at`）显示在顶部横幅；429 显示“注册请求过于频繁”；其他错误走 errorText |
| mock 与契约 | ✅（有 1 条 m） | `website` 与 `form_started_at` 不触发 extra=forbid，其他未知字段仍报 400，`agreements` 被忽略；`form_started_at` 不是整数时报 400；命中条件是 `website` 去首尾空白后非空，或者 当前时间 − `form_started_at` < 3000（含未来时间），不传则不检查；trigger 记为 website / too_fast / both，只记 trigger；命中时返回 201，响应体 `{id: 随机 uuid, username, status:"pending"}` 与正常注册的键集合相同，不建用户；closed 模式下即使命中也返回 503。阈值 3000 写成常量，不进配置 |
| 免责提示 | ✅ | 注册页固定展示，不提交 agreements |
| 上轮 m1（`/plans/{id}` 404） | ❌ 未处理 | `routes.tsx` 的 PLACEHOLDERS 仍只有 `['plans', '计划']`。本提交的范围不涉及这一项，转入下文 m4 |

时钟推导：设真实偏差为 θ（服务端时钟 − 本地时钟），服务端在其时刻 s 生成响应，`Date` 头取 floor(s) ≤ s；本地在时刻 r 收到响应，满足 r + θ ≥ s。所以 估计的 offset = floor(s) − r ≤ s − r ≤ θ，校正后的时间偏早，不会偏晚。

## 3. 问题

### B 级
无。

### M 级
无。

### m 级

| 编号 | 位置 | 问题 | 建议 |
|---|---|---|---|
| m1 | `lib/serverClock.ts`、`RegisterPage.tsx` | 如果 `/meta/registration` 的响应没有 `Date` 头（例如被代理去掉），offset 保持 0，`form_started_at` 就用本地时钟。本地时钟比服务端快 3 秒以上时，会被判为未来时间并静默命中蜜罐：真人看到“已提交”，但账号并没有建。uvicorn 和 nginx 默认都会发 `Date`，所以概率低，但后果是无提示地丢失注册 | 没有拿到有效 `Date` 头时不传 `form_started_at`（契约规定“不传则不做此项检查”），比用未校正的时间更安全。可以在 `serverClock` 里加一个“是否已校正”的标志 |
| m2 | `mocks/accountHandlers.ts` | mock 没有实现“IP 限速（命中也计数）”和“待审核数上限（503）”两步，判定顺序与契约不完全一致。这是原有缺口，不影响前端的可见行为 | 补上后再写一条“命中蜜罐也计入限速”的用例 |
| m3 | `mocks/accountHandlers.ts` | `website` 不是字符串时（例如数字）mock 不判为命中。契约中它的类型是 `string \| null`，后端会怎样处理（400 还是命中）没有写明 | 等契约明确后对齐，见“待对齐”第 2 条 |
| m4 | `app/routes.tsx` | 上轮的 m1 仍未处理：`/plans/{id}` 落到 NotFoundPage | 在 PLACEHOLDERS 中加 `['plans/:id', '计划详情']`，或者在 T-F17/T-F18 中一并处理 |

## 4. 待对齐（不算本提交的缺陷）

1. 契约中“待审核数上限（503）”没有写错误码（是 `REGISTRATION_CLOSED` 还是别的码）。前端目前收到未知的 503 会走 errorText；如果是 REGISTRATION_CLOSED，会显示“当前不开放注册”。需要由架构师在契约中补上（我这边的待办）。
2. `website` 是非字符串时后端怎样判定，契约没有写明。
3. 前端整体仍按 v0.2.7（`CONTRACT_VERSION`），本提交只实现了 v0.2.8 #11。v0.2.8 的其余条目（#1/#4/#12–#15 等）待安排。
4. 请后端评审跟进（不属于前端）：自述的遗留问题第 4 条说，后端“在校验阶段先占用邀请码再查重名”。如果确实如此，409 和蜜罐命中可能已经占用了邀请码，与契约中“命中时不消耗邀请码”冲突。请在评审 116cb7e 时核对。

## 5. 推送建议

本提交没有 B 级问题，干净检出全绿，**可以推送**。但要注意：main 上它前面还有尚未评审的后端提交 457a211 和 116cb7e，后面还有 307132b（docs）和 c55a42e（后端）。推送 main 会把这些提交一起带上，请先完成那几项评审，或者由用户确认。
