# 评审：05d8a16 feat(frontend): T-F12 候选信号卡补全

评审人：项目架构师　时间：2026-11-01（America/Denver）　方式：只读，/tmp 干净导出，pnpm 串行；对照契约 v0.2.9（§5.2、§7.8，#29/#31/#32）

## 结论：可推送；2 个 m 项后续跟进（无 B/M）

## 对照契约
| 功能 | 实现 | 契约 | 结论 |
|---|---|---|---|
| 状态标签 | `SUGGESTION_STATUS` 当前/已被取代/已失效/已过期 | §5.2 status 枚举 | 一致 |
| 取代关系 | 用 `supersedes_id` / `superseded_by_id` 给提示与跳转 | §5.2 | 一致 |
| 完整取代链 | `PendingContract` 占位，**不请求** `/chain` | §7.8 只写“返回取代链”，结构未定 | 合规 |
| 刷新 | POST `/suggestions/refresh {security_code}`，再 GET `?security_code&status=active&limit=1`；不读刷新响应体 | §7.8 请求体一致，可 409 | 一致（见 m2） |
| 409 | `SUGGESTION_REFRESH_TOO_FREQUENT` + `retry_after_s` →“刷新过于频繁，请 X后再试” | §7.8 / 错误码表 | 一致 |
| 跟踪 | GET `/suggestions/{id}/tracking`，t1/t5/t20 按 Stat 显示 | `{t1,t5,t20: Stat}`，Stat={value decimal\|null,n,window,small_sample} | 一致（见 m1） |
| 价格依据 | `PendingContract` 占位 | 契约写“并附各期价格依据”但无结构 | 合规 |
| 用户动作 | POST actions `{kind, trade_id:null, note}`，仅 viewed / dismissed；viewed 每会话一次，失败吞掉 | kinds viewed/dismissed/acted_trade_linked | 一致；acted_trade_linked 占位 |
| llm_call_id | 显示 | §5.2 explanation.llm_call_id | 一致 |
| 生成计划草稿 | 按策略 POST `/plan-drafts`；无信号/无权限/非 active 时禁用 | §7 plan-drafts | 一致 |
| 刷新按钮说明 | “按已缓存的数据重算…不额外拉取行情” | 与“刷新不触发外部拉取”口径一致 | 一致 |

- “待契约”占位：只显示标签，不造数、不发请求；mock 也不实现 `/chain`、不返回价格依据。**合规**。
- mock 的 tracking 为示例数据（仅 MSW 下），刷新 30 s 内 409，actions 校验 kind/trade_id/note 后返回 204。
- #29（风险文案）、#31、#32 前端列与本提交不冲突。

## 问题
- **m1（前端）**：`StatValue kind="ratio"` 用 `v.toFixed(2)`，0.003 这类收益显示成“0.00”，与页面自写的“数值按服务端原值显示（单位与口径待契约）”矛盾，且丢信息。改为原样显示服务端 decimal 字符串（或至少不舍入到 2 位），等契约定单位后再格式化。
- **m2（前端/后端，待契约）**：刷新后立即读列表。如后端刷新是异步的，会误报“已重算，当前卡没有变化”。契约未定义刷新响应，先记为待契约项；后端确认是同步完成还是返回任务态，前端据此调整（同步则无需改）。
- n：viewed 失败静默吞掉可以接受，建议 console.debug 便于排查。

## 验证
- c4329bc 导出（含本提交）：typecheck 0、lint 0、vitest 串行 584 通过 / 1 跳过。

## 谁做什么
- 前端：m1 改原值显示（小改，下个提交即可）。
- 后端：答复 m2（refresh 同步与否、响应体）；架构师下次契约修订时补 `/chain`、价格依据、refresh 响应的结构（本次不升版本）。
