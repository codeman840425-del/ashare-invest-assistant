# 测试收集与隔离检查

此入口由 T-13 收敛既有测试修复。只执行选定测试；`check_collection.py` 只收集，不执行测试体或 fixture，也不提供网络或数据库沙箱。收集时仍会导入模块和 conftest，须使用受控测试环境。

```powershell
python tests/tools/check_collection.py --output <仓库外目录>/collection.json
python -m pytest tests/tools/test_check_collection.py -q -p no:cacheprovider
python -m pytest tests/backend/integration/test_tb28_isolation_config.py tests/backend/integration/test_tb63_signals.py -q -rs -p no:cacheprovider
```

收集通过须同时满足 pytest 原生退出 0、收集错误为 0、收集数量至少达到下限。默认下限 1350 是历史防缩量门槛，不能当作当前完整节点清单或业务通过数；可用 `--min-collected` 提高。脚本清除继承的 `PYTEST_ADDOPTS` 与 `addopts`，固定 strict-config、strict-markers、importlib，单列 `skipped_collectors`。根外路径、缺失路径、非正下限均拒绝。导入前固定 `MAIRUI_MODE=replay` 并清空已废弃的 `MAIRUI_LICENCE`；不读取凭据文件。

可选依赖在场与缺失必须分别报告：schemathesis、hypothesis、requests 缺失时对应模块显式跳过，不能记为业务通过。完整依赖来自现有测试依赖声明，不由本工具安装。真实 CI 的忽略目录、testpaths 与插件仍需审查，数量下限不能替代逐节点核对。

隔离身份只支持同时设置 `AIA_TB28_PG_CONTAINER`、`AIA_TB28_PG_SOCKET`、`AIA_TB28_PG_VOLUME`；部分覆盖先拒绝。参数不授权创建或连接资源。元数据自检禁真实 Docker；T-B63 的真 PG 用例在 Windows 按平台跳过，Linux 仍须专用 PG、network=none、独立挂载和清理责任核对。不得连接用户库或共享库。

T-B86 两模块因 POSIX flock/权限在 Windows 跳过；Linux 证据须另行锁定 SHA。T-B70 本单只复验 synthetic_manifest、positions_preview 与 migration_head，三个写库集成用例不在验收范围。迁移版本由当前检出图的唯一 head 得出，零 head/多 head 仍拒绝。

## 修复来源

均通过正常 `cherry-pick -x` 保留原提交来源；不包含原 PR 的看板、历史报告或预研文档。

| 原入口 | 保留代码来源 | 边界 |
|---|---|---|
| #35 | `0ac8553` | 平台守卫与唯一迁移 head；不含数据库设施修复 |
| #38 | `3d7504d` | 收集守护与十项合成自检 |
| #42（原依赖 #38） | `ea3cc87`、`9491f63` | 四项收集修复；缺包显式跳过 |
| #48（接续 #11） | `7787441`、`e0d11eb` | #11 快照同步及严格负控；后者复用 T-T83 `cfea45a`，不得遗漏 |
| #62 | `69a869a` | Notification 测试与契约说明追加字段一致；不修改 mock 或业务 |
| #66 | `34ec476` | 隔离身份参数化与合成元数据拒绝用例 |

#43、#46、#73 是预研或历史证据；#80 是并行时序诊断及诊断工具。其材料归档在仓库外 `F:/workspace/team/reports/T-13/`，不作为业务修复合入。#80 继承的 F-10 业务提交也不属于本入口。
