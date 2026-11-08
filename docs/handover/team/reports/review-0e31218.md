# 评审 0e31218（前端：写请求 CSRF 双提交，契约 §1.3）

- 评审人：架构师；写于 2026-11-02 09:47 北京时间；只读评审。
- 依据：契约 §1.3（第 327 行）、§4 `403 CSRF_FAILED`、§9 第 1102 行；reports/csrf-frontend.md；后端 src/backend/app/auth/deps.py、sessions.py、api/v1/auth.py（只读对照）。

## 结论：**通过**（无 B、无 M；3 个 m）

## 逐项核对
| 项 | 结果 | 位置 |
|---|---|---|
| Cookie 名 `csrf_token`（非 HttpOnly） | 前端读 `document.cookie` 的 `csrf_token`，与契约、后端 `CSRF_COOKIE`（sessions.py:30；auth.py:136 httponly=False）一致 | src/frontend/src/api/client.ts:64–67 |
| 请求头 `X-CSRF-Token` | 一致（后端 sessions.py:31） | client.ts:91–94 |
| 所有写请求都带头 | 所有非 GET 都经 `request()`；apiPost/Put/Patch/Delete/Upload 都是它的封装；源码自查测试保证 client.ts 外没有裸 fetch 写请求、XHR、sendBeacon。唯一裸 fetch 是 errors.csv 下载（GET） | client.ts:83–140；api/accountQueries.ts:222；api/csrf.test.ts |
| 上传（multipart） | `apiUpload` → POST → 带头；不手写 Content-Type | client.ts:89–90、:140 |
| 登录、注册、登出、改密码 | 登出、改密码带头；登录与注册在登录前没有令牌，不带头（无 Cookie 时）。符合本轮裁定 4 的白名单 | api/accountQueries.ts:43、57、70 |
| 登录下发令牌 | 读响应体 `csrf_token` 存内存兜底，以 Cookie 为准；登出、改密码后清内存令牌、改读 Cookie | client.ts:59–67；accountQueries.ts:43 |
| `credentials` | 一律 `same-origin` | client.ts:102 |
| mock 顺序 | `/admin/*` 非管理员 404 → 管理员 CSRF 403；其他：401 → 403 ACCOUNT_NOT_APPROVED → 403 CSRF_FAILED。与后端 deps.py:145–158、:165–177 一致，也与本轮裁定 5 一致 | mocks/accountHandlers.ts；mocks/session.ts |
| 三者一致校验 | mock：有头、有 Cookie、头=Cookie、Cookie=会话令牌；后端常数时间比较（sessions.py:48–52） | — |

## 问题
- B：无。M：无。
- m1 登录、注册时如果浏览器里留着旧的 `csrf_token` Cookie，前端仍会带上头。按裁定 4 这两个端点不校验，无害；但 mock 的豁免清单应与契约白名单逐字一致（只豁免 `POST /auth/login`、`POST /auth/register`），并加一条断言“其他无会话写请求 → 401”（mocks/accountHandlers.ts）。
- m2 mock 没有 `POST /auth/password` 处理器（csrf-frontend.md 遗留 3）；补页面时一并补 mock：204 + 轮换 Cookie。
- m3 拿不到令牌时直接不带头，由后端 403（遗留 4）。可接受；收到 `403 CSRF_FAILED` 时建议提示“会话已变化，请刷新页面”，不自动重试写请求（避免重复提交）。

## 测试（干净导出，串行，第一个跑，跑完已删）
| 项 | 结果 |
|---|---|
| typecheck | rc=0 |
| lint | rc=0 |
| vitest | 34 个文件通过 + 1 跳过；530 通过 + 1 跳过（共 531），与前端自报 531/531 一致 |

## 谁需要做什么
- 前端：m1–m3。
- 后端：按裁定 4 把登录前白名单写死（login、register 不要求 CSRF，其余写请求无会话 → 401），按裁定 5 保持校验顺序；已有实现与之一致，补测试即可。
- 测试：用 `/admin/*` 非管理员 404 / 管理员 403、未登录写请求 401 两组用例对齐前后端。
