# T-T28：固定本机隔离环境的显式回归

依赖后端 `8e8525e`（或等效后续版本）、T-B63 报告指明的已有离线缓存/取证副本。
不是共享栈、生产部署或完整信号流水线验收；缺依赖直接失败，不能把失败改成 skip。

- `test_tb63_signals.py` 迁入原 30 例；29 个纯行为参数例，1 个调用原 tb60 的真实 PG 45 项断言。
- PG 连接前检查 `tb58-isolated-pg3` 的固定卷/socket、running、network=none、无端口映射、无其他容器挂载冲突。
- tb60 仅允许专用库/socket，已有 app/market schema 即拒绝；DDL、合成候选、事件、savepoint 操作最终回滚。
- 未使用 Redis；不启停任何容器，不访问环境 DSN/密钥，不 mock 信号准入或写入链路。
- 后端不在当前分支时，可设置 `AIA_BACKEND_DIR` 指向已核验的既有离线快照；不能擅自连共享库补环境。

`test_tb58_replay_calibrated.py` 只读 `/tmp/tb63-replay-h2r0wxj5` 中已有副本（可显式指定
`AIA_TB28_EVIDENCE_ROOT`，必须是 /tmp 下专用副本）；先比对 62 个原始输入摘要，之后仅对 pytest 新建副本重放。

历史 tb58 的两个“非⑨分析完全不变”断言照实保持失败记录（58 过/2 败），不改 selfchecks。
两份旧分析早于 T-B59/7c0548a：新日历不猜日期、名单草稿不冒充正式名单、CDR逐证券签收使非⑨区也改变。
新验收比较整份分析的 canonical SHA 与 T-B63 已验证的 T-B59 更正产物；不是删除非⑨断言或整段忽略。
版本化 share_class_list 从本机 Git `8e8525e` 对象读取并核对 SHA，仅作真实输入配置路径注入；不替换分析函数。
快照缺根 config 的场景不应自动被误认为业务回归，因此测试显式固定输入版本。

本轮实际命令/原始日志见 `/workspace/team/reports/T-T28.md` 与 `T-T28-logs/`。
