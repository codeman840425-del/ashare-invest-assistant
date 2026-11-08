# T006f 架构师审核与代提交（3cb8af1）
- horizon_classifier.md、catalog.md 与契约 v0.2.6（HorizonCap #10、§验收 v0.2.6）一致；yaml 可解析；gitleaks 无泄漏。
- classifier_version：保持 1.2.0，不升版本。理由：规则与分数不变；caps 输出的不兼容变化由契约版本 v0.2.6 标识；尚无按 1.2.0 持久化的线上评估记录。之后只要分数或规则有变化，就必须升版本。
- S-03：仍从自动匹配中排除，默认关闭，只能手动启用，开关旁固定展示风险说明。研究员的写法正确。
- 顺带修正契约 v0.2.3 验收项中残留的 novice 夹具 `kind: requires` 断言（已作废，标删除线）。
