# 评审 d0c7ccb（前端：review-b23401a 修复）

- 评审人：架构师；写于 2026-11-02 09:47 北京时间；只读评审，未改代码。
- 依据：/workspace/team/reports/review-b23401a.md（m2、m3、N1–N8），契约 v0.2.9。

## 结论：**通过**（无 B、无 M）

## 逐项核对
| 项 | 结果 | 位置 |
|---|---|---|
| N1 原型链键 | 已修：改用 `Object.hasOwn` | src/frontend/src/features/signals/stateTransition.ts:18、:25 |
| N2–N4 证据 chip 键盘与冒泡 | 已修：`role="button"`；Enter/空格 `preventDefault`+`stopPropagation`；onClick 也阻止冒泡 | components/EvidenceChips.tsx:30 附近 |
| N5 日报卡片可访问性 | 已修：section 去掉 `role=link`，加 `aria-labelledby`；标题改为真正的 `<Link>`，sr-only“：查看候选信号卡”说明去向；chip 不在链接内 | pages/DailyReportPage.tsx:91–128 |
| N6 路由切换后的过期回调 | 已修：`pathRef` + `alive` 守卫 | pages/DailyReportPage.tsx:50–57 |
| N7 blocked 的允许转移 | 已修：blocked → `['released','dismissed']` | mocks/planHandlers.ts（signalAllowed） |
| m2 管理端证书定位 | 已修：续加载定位，上限 `FOCUS_MAX_PAGES=40`，searching/missing/hidden 三种提示 | pages/admin/AdminDataLicencesPage.tsx:69–83、:159–164 |
| m3 先 trim 再校验 | 已修 | mocks/accountHandlers.ts:280 |
| N8 全局测试超时还原 | 已还原：setup.ts 删 `asyncUtilTimeout`，vite.config.ts 删 `testTimeout`。改为 test/preloadRoutes.ts + 21 个文件 `beforeAll(preloadRoutes, 30_000)`；新增局部超时仅 t-f17.test.tsx:90（5000ms），review-b23401a.test.tsx:80/88/95 为新文件自带 | src/frontend/src/test/setup.ts、vite.config.ts |

## 问题
- B：无。M：无。
- m1 带可访问名称的 `<section aria-labelledby>` 会成为 region 地标，日报每张卡片一个地标，读屏地标列表会很长。建议改 `<article>` 或去掉 aria-labelledby（DailyReportPage.tsx:91 附近）。
- m2 chip 有 `role="button"` 但按 Enter/空格只阻止默认、无动作；要么给动作（打开证据），要么不要 button 角色（EvidenceChips.tsx:30）。
- m3 续加载定位达到 40 页上限后，用户手动“加载更多”不会再自动定位到目标行（AdminDataLicencesPage.tsx:69–83）；提示文案已说明，可接受，后续改服务端筛选（plan 第 9 节问题 72）时一并消失。

## 测试（git archive 导出到 /tmp 干净目录，串行，跑完已删）
| 项 | 结果 |
|---|---|
| typecheck（app/node/test 三个 tsconfig） | rc=0 |
| lint（eslint .） | rc=0 |
| vitest | 31 个文件通过 + 1 跳过；466 通过 + 1 跳过（共 467），与前端自报 467/467 一致（跳过的是既有的条件跳过用例） |

## 谁需要做什么
- 前端：m1–m3 可在下一次前端提交顺带处理，不阻塞。
- 后端、测试：无。
