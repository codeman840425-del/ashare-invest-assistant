# git stash 自查（前端）——“T-F17 WIP”去向

- 检查时间：2026-11-02 09:46（北京时间）。全程只读，用到的命令只有 `git fsck --unreachable --no-reflog`、`git log`、`git show`、`git diff`、`git merge-base`、`git reflog`。**没有执行 stash pop、apply、drop，也没有改动任何 ref。**
- 当前 `git stash list` 为空，所以 stash 都成了悬空提交。

## 结论
**“T-F17 WIP”就是悬空提交 9aafea1**（On main: T-F17 WIP，2026-11-02 07:36 北京时间，基于 67d123a）。它的前端内容已**全部包含在 b34260f** 里（T-F17，08:00 北京时间，是 HEAD 的祖先）。没有遗漏的内容，不需要恢复。

| 部分 | 文件 | 与 b34260f 的对比 |
|---|---|---|
| 工作区改动（9aafea1 相对 67d123a） | strategyTypes.ts、strategyHandlers.ts、todayFixtures.ts、SuggestionDetailPage.tsx、t-a08.test.tsx | 内容完全相同 |
| 同上 | routes.tsx、mocks/fixtures.ts、mocks/handlers.ts、styles.css | stash 新增的行全部出现在 b34260f 里（缺 0 行） |
| 暂存区（6b99e10） | — | 与基线相同，没有暂存内容 |
| 未跟踪文件（e1a8610） | StatValue.tsx、LifecycleBadge.tsx、ReasonCard.tsx、CandidateSignalsPage.tsx、signalQueries.ts、signalLabels.ts、lib/signals.ts | 内容完全相同 |
| 同上 | mocks/signalHandlers.ts | b34260f 只是把 `let cur` 改成了 `const st = { cur }`，逻辑相同 |
| 同上 | CandidateSignalDetailPage.tsx | b34260f 只把 `as object` 改为 `as ButtonProps`，并给表格外面包了一层 `<div className="stat-wrap">` |

和 HEAD 比，少数行不一样，原因都是后续提交有意修改了同一处代码，不是内容丢失：
- 53468a5（T-F18）、7a3e9cb（v0.2.9 #10 的 scope 校验和 #6 的状态历史）、d0c7ccb、0e31218 都改过这些文件。
- 举例：t-a08 里那行注释被后来的提交改写了；strategyHandlers 的 `scope` 那一行被 v0.2.9 #10 的 400 校验替换了。

## 其他悬空的 WIP / On 提交（`--no-reflog`，共 7 个）
| 提交 | 标题 | 前端内容去向 |
|---|---|---|
| 0e41ca3 | On main: T-F03 WIP (paused for T-F02b) | 较早的 T-F03 草稿，已被 b79ce80（T-F03，06:15 北京时间，HEAD 的祖先）取代：routes 后来改成懒加载，handlers 只差一行注释 |
| 96b0145 | On main: T-F03 WIP (before T-F22) | 未跟踪部分 47a1ccd 和 b79ce80 基本一致。剩下的差别：注释里的契约版本号从 v0.2.5 改成了 v0.2.6，指数示例成交额的写法，以及一处封顶 Tooltip 的写法 |
| 9c2ff89 | On main: v029-sync-wip (frontend only) | 20 个文件全部包含在 7a3e9cb 里（16 个完全相同，4 个缺 0 行） |
| f207132 | WIP m11 + Me v0.2.6 | 只改了 tests/backend，没有前端内容 |
| 130af86 | On test/T-T01: tt22-wip | 只改了 tests/backend，没有前端内容 |
| c2195d5 | WIP on main: 81e62ea（Phase 0） | 只改了 src/backend/probes，没有前端内容 |

## 已知的五个 hash
| 提交 | 实际是什么 |
|---|---|
| 0e41ca3 | 确实是 stash（T-F03 WIP），见上表 |
| f2e153d | **普通提交**，不是 stash：T-F03 rebase 前的原始版本（main<at>{61}）。rebase 后同标题的提交是 b79ce80，已在 HEAD 中 |
| 7c228d1 | 普通的 docs 提交（main<at>{94}），rebase 后是 fb583bf，已在 HEAD 中 |
| aca3c34 | 测试分支 test/T-T01 上 rebase 时 pick 出来的提交，不是前端内容 |
| d745148 | 测试分支 test/T-T01 上的提交，不是前端内容 |

后四个都还挂在 reflog 上，所以只有不加 `--no-reflog` 时才会被列为不可达。

## 需要谁做什么
- 编排者：T-F17 的内容已经在 b34260f 里，可以视为结案。是否清理悬空对象（gc）由仓库负责人决定，前端这边不做。
- 测试分支（T-T01）上的 aca3c34 / d745148 由测试负责人自己确认。
