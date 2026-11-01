# tests/e2e —— Playwright 端到端测试

- 配置：`playwright.config.ts`，桌面 Chromium，**1440×900、colorScheme=dark**、zh-CN、Asia/Shanghai（plan §8.0）。
- 首次：`pnpm -C tests install && pnpm -C tests e2e:install`（下载 chromium；Linux 缺系统库时用 `pnpm -C tests exec playwright install --with-deps chromium`）。
- 运行：`pnpm -C tests e2e`
  - 未设置 `E2E_BASE_URL`：自动起本地静态页（`static/`，`python3 -m http.server`，端口 `E2E_STATIC_PORT` 默认 4399），跑 `smoke.spec.ts`；`app.spec.ts` skip。
  - `E2E_BASE_URL=http://127.0.0.1:8080 pnpm -C tests e2e`：对已启动的站点（deploy/scripts/up.sh，nginx 8080）跑 `app.spec.ts`；`smoke.spec.ts` skip。
- 站点必须处于 `MAIRUI_MODE=replay`；E2E 不得触发真实麦蕊调用。
- 报告与失败截图/trace 输出到 `tests/playwright-report/`、`tests/test-results/`（已 .gitignore）。
