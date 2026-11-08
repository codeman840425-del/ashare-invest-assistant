# tests/frontend —— 前端单元测试（vitest + testing-library）

- 运行：`pnpm -C tests install && pnpm -C tests test`（plan §6 目标形态是 `pnpm -C src/frontend test` 指向本目录，
  等 src/frontend/package.json 落地后迁移）。
- 环境：jsdom；`setup.ts` 注入 jest-dom 断言、默认深色 `matchMedia`、并把 `fetch` 换成"一调用就失败"的桩，
  需要后端数据时用 `vi.fn()` 显式 mock（契约字段以 docs/api-contract.md 为准，金额/价格为十进制字符串）。
- 别名 `@` → `src/frontend/src`。
- 文件命名：`*.test.ts(x)`；`example.test.ts` 只是示例，前端组件落地后可删除。
