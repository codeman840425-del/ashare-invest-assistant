# T-T27：仅准备，不执行

目标固定 `http://127.0.0.1:8080`，独立配置，1440×900、深色；不启动/重建任何栈。
此目录的静态发现不会读取凭据，也不连接目标、注册、登录、审核或赋权。

## 静态校验

使用 tests/package.json 固定的 Playwright 1.64.1：

```sh
pnpm -C tests exec playwright test --config e2e/t-t27/playwright.config.ts --list
```

## 执行前阻塞（不能把环境变量当授权）

1. 等用户另行通知，编排者确认针对独立 aia-t01 栈的执行授权与测试账号生命周期。
2. 获准后先核对 `/workspace/team/runtime/T-O15/viewer-cred` 实际文件/目录和字段格式；当前适配器故意报阻塞，不读取、不假设格式。
3. 后续实现内存凭据适配，不在代码/环境变量/报告/断言中存放或输出原值；不保存 storageState/trace/video。
4. 可选 `registrationSetup`、`adminSetup` 默认为 undefined，未实现业务、SQL 或 CLI。注册提交/审核/管理员身份准备必须逐项批准后另接；默认网络保护仍禁止这些写请求。
5. 只有以上条件完成才能启用 `T_T27_EXECUTION_APPROVED=yes`；当前不要执行（包括不带 `--list` 的“试运行”）。

## 范围与保护

入口依据 `src/frontend/src/app/routes.tsx`、`app/nav.ts`、`features/terminal/WatchTable.tsx`：
`/login`、`/register`、`/portfolio`、`/today`、`/terminal`（自选/盘中建议）、`/strategies`、`/daily-reports`、`/portfolio/import`、`/notifications`、`/admin/users`、`/admin/ingest`、`/admin/data-licences`。
未伪造 `/watchlist`、`/intraday` 路由。注册仅展示页面，导入仅打开向导，不创建账户/上传/确认；通知不标已读、策略不启用、关注不新增。
浏览器 HTTP 和 WebSocket 只允许 127.0.0.1/localhost:8080，禁止 Service Worker，写方法默认阻断（仅为未来获准登录预留 POST /api/v1/auth/login）。
截图只在未来获准运行时全页写入 `/workspace/screens/01-login.png` 至 `13-admin-data-licences.png`；截图名以 spec 为准，当前无截图和页面可用性结论。
登录截图在填写之前，自动失败截图关闭；管理端无权限不得伪装通过或自动赋权。
