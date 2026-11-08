# 评审 d9c045f（前端：同步契约 §4 的 414 URI_TOO_LONG）

- 评审人：项目架构师；时间：2026-11-01 20:47（America/Denver，UTC-7）
- 方式：只读。干净导出后跑 eslint、tsc、vitest、pnpm audit；没有推送。
- 对照：契约 §4 错误码表（4b40e5c，v0.2.9 #34）。

## 结论：可以推送（要和 787e453 一起推）

只改了 1 个文件 3 行：src/api/errorCodes.ts 加了 `URI_TOO_LONG: 414`，现在一共 62 个错误码。恢复了"ERROR_CODES 与契约 §4 逐行一致"的校验，把 787e453 留下的那个 vitest 失败修好了。

## 1. 实测
| 项 | 结果 |
|---|---|
| eslint / tsc | 0 / 0 |
| vitest | 39 个文件 / 621 passed，1 skipped |
| pnpm audit | 通过 |

## 2. 问题
**B / M / m：无。**

## 3. 推送后 CI
- frontend：绿。
- contract --meta-json：仍然是红的（后端 /meta/enums 缺枚举和 414，归后端 T-B50，d3be426 修复）。
- backend / migrations：不涉及。
