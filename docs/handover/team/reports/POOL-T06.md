# POOL-T06：Notification mock契约测试修复（北京时间2026-11-11）
- 基线冻结origin/main=465e02046fa8d971897603742497444f884e89a2；分支ds/T06；代码冻结69a869a7d08d7ba51129337017b60b0f2b146f76，仅本地未推送/未合入。
- 原main独立复现：src/mocks/contract.test.ts 34 passed/1 failed，准确Notification字段集合缺version/merged_count/updated_at/refs；不依赖F-08改动，未使用stash。
- 根因：测试只解析api-contract §5.1旧内联结构；§7.8已追加merged_count/updated_at/refs及version，类型与projectNotification已实现投影，mock并未过期。
- 仅改src/frontend/src/mocks/contract.test.ts：PROSE_ADDED补四字段，继续严格键集合相等；两项附加用例核文档出处、整数≥1、有效时间与refs数组/上限。
- 原契约和mock不改，不删除合法字段迁就旧结构；未知字段仍拒绝。
- 命令：使用bundled Node与pnpm执行pnpm exec vitest run src/mocks/contract.test.ts --reporter=verbose；依赖pnpm install --frozen-lockfile --offline，仅安装本worktree node_modules、锁文件未变。
- 冻结终验37 passed/0 fail/0 skip；与基线相比原35项修复1败+新增2项，未跑全量前端/coverage/build。
- 负控准确过滤逐字一致的Notification节点：临时合成投影删除version → 1 failed/exit1；添加synthetic_unexpected_field → 1 failed/exit1。
- 负控仅独立树fixtures.ts短暂扰动，finally逐字节恢复；最终git状态本体只含授权测试改动，无stash/他人索引操作。
- 限制：当前NOTIFICATIONS投影refs为空，不能据嵌套循环宣称非空ref语义已有覆盖；本单核心覆盖是顶层追加字段及缺/多字段严格拒绝，不替代通知运行时验收。
- 证据：F:/workspace/team/status/T06-baseline.log、T06-frozen-final.log、T06-negative.json及T06-negative-{missing-version,unexpected-field}.log；负控脚本同目录T06-negative-control.py。
- secret_scan授权测试+报告/看板0阻断/0告警；git diff --check通过；无业务代码改动、无库/真实数据/麦蕊/栈操作。
- DeepSeek：未用，契约来源与负控均本地核对。
申请新任务：r2发布后的R1–R5冻结核验优先；请编排者验收并安排推送/PR。
