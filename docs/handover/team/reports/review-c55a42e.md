# 评审：c55a42e（T-B02y 补丁：0009 回填 paused/archived + security_type 顺序）

- 评审时间：2026-11-02（UTC+8）
- 评审方式：只读；`git archive` 导出到 /tmp，主工作树未动；迁移在临时 PG16（TimescaleDB 2.31.0）容器中实测，测完已删除容器
- 自报：/workspace/team/reports/T-B02y.md
- 时间顺序说明：本地 main 上 c55a42e（07:12）实际晚于 457a211 / 116cb7e（07:05）和 307132b（07:10），任务单把它列在第一位，但它是三者里最后提交的。origin/main 仍为 0cb78ad，0009 尚未推送，原地修改 0009 可以接受。

## 结论：**通过**

## 问题表

| 编号 | 位置 | 问题 | 原因 | 修复建议 | 负责 |
|---|---|---|---|---|---|
| m1 | migrations/versions/0009_t_b02y_contract_v027.py | 已经跑过旧版 0009 的环境（若有）不会再执行回填，paused_by / archived_at 仍为空 | 回填是原地改进 0009，alembic 不会对已在 0009 及以上的库重跑 | 推送前确认没有任何环境的 alembic_version ≥ 0009；如果有，单独补一个幂等的回填脚本或 0011 | 后端 / 运维 |
| m2 | — | 提交顺序与任务单顺序不一致（见上） | — | 仅记录，无须修改 | — |

无 B / M。

## 测试方法（真实 PG16）
1. 空库：upgrade head（=0010），`alembic check` 无差异；head 时 104 个触发器，0008 时 98 个；head → 0008 → head 后触发器与函数 md5 一致；downgrade base 后 0 张业务表，再 upgrade head 仍一致。
2. 回填：停在 0008，造 6 行策略实例：
   - paused（无 paused_by）→ 回填为 `paused_by=user` ✓
   - archived，有两条 archived 事件 → archived_at 取 max(at)=10-06，后面的 paused 事件被忽略 ✓
   - archived 无事件 → 取 confirmed_at ✓
   - archived 既无事件又无 confirmed_at → 取 created_at ✓
   - active / proposed 不动 ✓
   upgrade 0009 后违规行为 0；downgrade 到 0008 正常；再 upgrade，违规行仍为 0。
3. security_type 顺序：`/meta/enums` 输出 `stock, cdr, etf, index`，与契约 v0.2.8 一致。
4. 测试数据里的密文/HMAC 都是随机 md5 占位，不含任何证书值。

## 检查表

| 检查项 | 结果 |
|---|---|
| 0009 在 0008 上回填 paused 行 | ✓ |
| 0009 回填 archived 行（事件 → confirmed_at → created_at 三级回退） | ✓ |
| downgrade 0009 → 0008 | ✓ |
| 再 upgrade 0 违规 | ✓ |
| security_type 顺序 stock/cdr/etf/index | ✓ |
| alembic check 无漂移 | ✓ |
| ruff / mypy / uv sync --frozen（7afbc06） | ✓ |
