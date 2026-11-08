# 评审 83a031c（T-B10：研究候选 /candidates 六端点 + 3 枚举 + 0016）

- 评审人：项目架构师；2026-11-01（America/Denver）
- **结论：通过（附 m）**。可以推送，建议与 0f8129b 在同一次推送里出去（0f8129b 缺的 3 个枚举由本提交补上）。

## 核对 §7.7A / T-A11
- 6 个端点都在；`_owned` 对他人 id 返回 404 ✔
- 重复 → `409 CONFLICT {field:"security_code", existing_id}` ✔；判定顺序 ③状态机 → ④VERSION_CONFLICT，与契约一致 ✔
- 终态 → `409 INVALID_STATE_TRANSITION {from,to,allowed:[]}` ✔
- ETF/指数 → **400** `VALIDATION_ERROR`（issue `security_type_not_supported`），与契约一致（“422”的说法不对）✔
- `_new_version`：先 rc.generate，再写快照（purpose=candidate，user_id=本人，licence_id=null），再插版本，最后写 claims/claim_links ✔；符合 plan 3.3 写入方验收
- 删除用户 CLI 覆盖 research_candidates（:166 先清 current_version_id）、candidate_versions（:217-218,324）、claim_links（:245）、claims（:246）、data_snapshots（:303）✔
- 0001 基线里已有 candidate_versions 不可变触发器和 CHECK ✔；限流 120/h ✔

## 0016 降级/升级实测（自起 timescaledb 2.31-pg16 容器，用完已删）
- upgrade head（0001→0016）✔；部分唯一索引 `uq_research_candidates_user_security_open … WHERE status IN ('researching','watching')` ✔
- 同用户同证券第二条 open → UniqueViolation ✔；dropped 同代码 → 允许 ✔
- downgrade 0016→0015→0014 ✔（索引被删）→ upgrade head ✔
- 降级状态下插入重复 open，再 upgrade：0016 报 UniqueViolation，**整次 upgrade 回滚到 0014**（不留半截状态）；清掉重复后 upgrade 成功 ✔
- `alembic check`：No new upgrade operations detected ✔

## 问题
- m1 `app/research/content.py:53` `_RISK_TEXT["delisting"]` 写的是“退市风险警示”，应为“退市整理”（契约 v0.2.9 #29）——后端
- m2 RC4 行业集中：未实现，也没出 gap；行业数据接入前必须出 gap（plan 4.2 新增段）——后端
- m3 `_duplicate`：并发对手回滚时 `existing_id` 可能为 null（契约允许 null，记录即可）
- m4 0016 没有预检，遇到重复只报 IntegrityError；在共享库执行前由运维先跑重复查询（T-O11-rulings §4）——运维

## 测试
- ruff、mypy、静态检查通过；`check_contract --meta-json` 通过（3 个枚举已补上）
- check_fixtures 的 `fmt_a` 3 条 error 在 5 个提交上都一样，是已有问题，不是本提交引入的
- 测试员全套：887 passed / 9 failed / 100 skipped / 36 xfailed / 1 xpassed
  - 其中 2 条是预期内失败（T-B10.md 已说明：alembic head 已知列表、realtime 快照）
  - 另外 7 条是环境原因：测试导出目录缺 `config/imports.yaml`、`docs/api-contract.md` 等路径；contract_live 打到了本机其他代理的 <host>:8080 nginx（414），与本提交无关

## 谁做什么
- 后端：m1、m2
- 运维：m4
- 测试员：alembic head 已知列表加上 0016
- 前端：显示 `planned`
