# T-B16b 分类器 caps.kind = gate | data_missing（契约 v0.2.6 / T-A07 §5 / T006e 裁定 1–2）

- 作者：后端；日期：2026-11-02；提交：38ed2b5（只在本地，未推送）
- 范围：config/horizon_classifier.yaml、src/backend/app/db/tables/strategy.py、migrations/versions/0006_t006e_caps_kind.py

## 改动
1. `HORIZON_CAP_KINDS = ("gate", "data_missing")`（删 `requires`）。`caps_shape` CHECK 另加两条：`kind=gate` 时 `rule_id` 匹配 `^HG[1-6]$`、`inputs_missing=[]`（契约 §5.1 HorizonCap）。
2. 迁移 0006（down_revision 0005）：替换 `ck_symbol_horizon_assessments_caps_shape`。表只追加，旧行无法改写：库里已有 `kind=requires` 元素时升级**明确失败**（check_violation），downgrade 遇 `gate` 同理。
3. `horizon_classifier.yaml` 逐字同步 plan §6.1 新增的三条 T006e 注释（HG 记 gate、IT0 的 else_score 是分数不进 caps 且 hints 独立、LG0/LG0B 记 data_missing）。

## 版本
- 规则内容未变（只加注释），plan §2.5.3 与契约 v0.2.6 仍写“当前版本 1.2.0 / version_no 3”，T-A07 §5 没有要求升分类器版本 → **不升**。契约版本 v0.2.6（`/meta/enums.version`）随 T-B45 的枚举/错误码一起同步。

## 还没有的部分（如实说明）
- 分类器**运行时尚未实现**（app 中没有求值代码），所以“IT0 不进 caps、hints 与分数独立、HG1–HG3 记 cap 0”目前只体现在数据库约束与配置注释上；实现分类器的任务须按契约 v0.2.6 输出。测试用例（T-T22）：无底仓 → intraday_t 0 分且 caps 无 IT0；novice → hints 仍含 IT0C；ST → `{kind: gate, rule_id: HG4, cap: 59}`；财报不足 → `{kind: data_missing, rule_id: LG0, cap: 59}`。

## 验证
- /tmp/tb02/selftest_t006e.py 22/22（隔离库 0006：gate HG1/HG4/HG6、data_missing LG0/LG0B/null 接受；requires、gate+IT0/null/HG7/非空 inputs_missing、未知 kind、cap 越界拒绝；迁移守卫；迁移约束与 metadata 逐字一致）。
- 0005→0006→0005→0006 往返通过，`alembic check` 无差异。
- 其他自测：tb16 125/125、tb03a 38/38、xff 21/21、api 通过（契约错误码计数按 v0.2.6 改为 59）。
- 测试套件：501 passed / 215 skipped / 3 xfailed / 1 xpassed / **3 failed**，3 个失败都与本任务无关、提交前已存在（v0.2.6 文档先行）：`test_snapshot_equals_plan_block[ingest]`（测试员的快照 config_defaults/ingest.yaml 未同步 plan v0.2.6，需测试员更新）、`test_contract_header_version` 与 `test_contract_parsers_sanity`（测试写死 v0.2.5 / 56 个错误码，需测试员更新）。

## 需要他人
- 研究员：horizon_classifier.md 的 caps kind 说明改为 gate | data_missing。
- 前端：封顶说明按 kind（gate / data_missing）显示（已在改 horizonCaps.ts）。
- 运维：共享库需要执行 0005、0006（我未在共享库上执行）。
