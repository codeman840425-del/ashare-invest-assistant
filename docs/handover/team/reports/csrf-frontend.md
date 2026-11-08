# CSRF 双提交（契约 §1.3，并入 v0.2.9）——前端

- 提交：**0e31218**（父 07b8d74），2026-11-02 09:38 北京时间，16 个文件，+304/−56，只含 src/frontend/。未 push。
- 报告写于 2026-11-02 09:45 北京时间。

## 契约依据
- §1.3（约第 327 行）：登录在响应体和非 HttpOnly Cookie `csrf_token` 里都返回令牌；所有 POST/PUT/PATCH/DELETE 都要带 `X-CSRF-Token`；缺少或不一致返回 `403 CSRF_FAILED`；请求头、Cookie、会话令牌三者一致，以 Cookie 为准。
- 约第 1061 行：非管理员访问 `/admin/*`（包括缺 CSRF 的情况）一律 404。
- 约第 1102 行：请求头与 Cookie 一致但和会话令牌不同 → 403。
- `/auth/logout`（🔒）→ 204；`/auth/password`（🔒）→ 204，并轮换 sid 和 csrf_token（前端之后重新读 Cookie）。

## 写路径核对（api/client.ts）
- 所有写请求都走 `request()`，经过 apiPost / apiPut / apiPatch / apiDelete / apiUpload 这几个封装，业务代码里共 29 处调用。覆盖登录、注册、登出、改密码、/accounts、/trades、/trades/{id}/void、/imports（上传）、/me/profile、/me/data-licence（PUT/PATCH/DELETE）、/admin/users/{id}（PATCH）、/admin/data-licences/{id}/{op}、/candidates、/candidates/{id}/versions、/plan-drafts（含 confirm/discard）、/notifications/*、/candidate-signals/{id}/dismiss、/non-executable-reasons/{id}/release、/strategy-instances（含状态切换）等。
- `request()` 的做法：
  - 对所有非 GET 请求加 `X-CSRF-Token`。取值顺序：先读 Cookie `csrf_token`，读不到再用登录响应里的令牌（内存兜底）。
  - fetch 一律用 `credentials: 'same-origin'`，同源下会带上 Cookie。
- 结论：**client 原本就满足两项要求，这次没有改 client.ts。** 新增的源码自查测试保证 client.ts 以外没有直接用 fetch 发写请求，也没有用 XMLHttpRequest 或 sendBeacon。
- 唯一的裸 fetch 是 errors.csv 下载，它是 GET，不需要 CSRF。

## mock 的执行顺序（src/mocks/accountHandlers.ts、session.ts）
1. `/admin/*`：非管理员 → 404（不管 CSRF 对不对）；管理员但 CSRF 不通过 → 403 CSRF_FAILED。
2. /meta、/health、/auth/login、/auth/register 不做 CSRF 校验（见遗留问题 1）。
3. 未登录 → 401；账号未批准 → 403；之后才校验 CSRF，不通过返回 403 CSRF_FAILED。满足以下全部条件才算通过：
   - 有请求头；
   - 有 Cookie；
   - 请求头 = Cookie；
   - Cookie = 会话令牌。
4. 登录时轮换令牌，令牌同时放在响应体和 `Set-Cookie` 里；登出清除 Cookie 和会话令牌。
- 为什么 mock 直接读写 document.cookie：MSW v3 在 node 里不会把 mock 的 Set-Cookie 写进 document.cookie，所以 mock 自己读写 document.cookie 来模拟浏览器。credentials 为 omit 时不读 Cookie。

## 测试（src/api/csrf.test.ts，20 个）
- 逐个写方法检查：POST、带 Idempotency-Key 的 POST、PUT、PATCH、DELETE、multipart 上传、直接调 request() 发 POST，都断言 `X-CSRF-Token` 等于 Cookie 值，并且传给 fetch 的 `credentials` 为 `same-origin`。
  - 测试环境的 fetch 包装不保留 Request.credentials，所以从 fetch 的入参里读。
- 其他 client 行为：
  - GET 不带 CSRF 请求头。
  - Cookie 被清除后，用登录响应里的令牌兜底。
- 接真实 mock：
  - 登出带请求头 → 204，之后的写请求 → 401。
  - 上传、PUT、PATCH、DELETE、POST 都通过 CSRF 校验。
- mock 应当拒绝的情况，都返回 403 CSRF_FAILED：
  - 缺请求头（四种方法逐一测）；
  - 请求头与 Cookie 不一致；
  - 只有请求头、没有 Cookie；
  - 请求头 = Cookie，但和会话令牌不同；
  - 登出缺请求头 → 403，会话保留。
- 登录：不带请求头也能登录（暂定豁免）。登录后令牌轮换，响应体里的令牌等于 Cookie，旧令牌失效。
- `/admin/*`：非管理员缺 CSRF → 404；管理员缺 CSRF → 403。
- 源码自查：client.ts 以外没有直接 fetch 写请求，也没有 XHR 或 beacon。
- 原有测试的改动：12 个测试文件里直接调接口的写请求，原来不带请求头，开启校验后有 53 个失败。现在改用 `src/test/apiFetch.ts`，它像 client 一样从 Cookie 取令牌放进请求头。没有包装全局 fetch，以免把 client 的问题掩盖掉。

## 结果
| 项 | 工作区 | 干净检出（/tmp/wt-verify <at>0e31218） |
|---|---|---|
| typecheck | 0 | 0 |
| eslint --max-warnings=0 | 0 | 0 |
| vitest | 35 个文件，531/531 | 35 个文件，531/531 |
| ignored-sources | — | 错误 0，告警 4（与之前相同） |
| pnpm audit | — | 1 个 moderate（与之前相同） |
| build + check:dist | — | 共 52 个文件，0 命中；dist-mock 反向自检有效（20 个标记） |

提交前扫描：secret_scan 共 219 个文件版本，暂存区 16 个，阻断 0、警告 0；gitleaks 三次都是 no leaks；禁用词和 11 位数字均 0 命中；暂存区只含 src/frontend/。

## 遗留问题（不改契约，请架构师裁定）
1. **登录前的请求**：契约没有写登录、注册的例外，但登录前不可能拿到令牌。mock 暂时豁免 /auth/login 和 /auth/register。请确认后端是否同样豁免，或者改为先发一个 GET 下发 csrf_token（前端已经支持从 Cookie 读取）。
2. **校验顺序**：mock 先 401 和未批准 403，再校验 CSRF。未登录的写请求返回 401 还是 403 CSRF_FAILED，契约没有写明。
3. **mock 没有 `/auth/password` 处理器**，请求会落到 404 兜底。前端的 useChangePassword 成功后会清掉内存令牌，之后重新读 Cookie。目前没有页面调用这个 hook，后续补页面时再加 mock。
4. **client 拿不到令牌时**（Cookie 和内存都没有）直接不带请求头，由后端返回 403。没有做先获取令牌再重试的逻辑。

## 需要谁做什么
- 后端（T-B03 等）：按 §1.3 对所有写请求实现双提交校验，并确认第 1、2 条的行为。
- 架构师：裁定遗留问题 1、2，必要时补进契约文字。
- 测试：可以用 `/admin/*` 非管理员 404 和管理员 403 这对用例，与后端实现对齐。

## 他人提交（未触碰、未 add）
- 0e31218 之前：07b8d74 T-B47-R10（09:32）、a8e055b、db486aa（09:31）。之后：2a9d141 T-O13 deploy（09:40 北京时间）。都没有涉及 src/frontend。
- 工作区里有他人未提交的改动（deploy/、scripts/ci/、src/backend/ 等），没有 add。
