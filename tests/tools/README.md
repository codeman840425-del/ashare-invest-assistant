# 收集守护（池单 T-02）

在已安装项目测试依赖的 Python 环境运行：

```powershell
python tests/tools/check_collection.py --output collection-summary.json
```

从任意目录运行时，脚本默认定位自身所在仓库的 `tests/` 整树；相对输出路径以调用目录为准。仅执行 `--collect-only`，不执行测试体或 fixture，不启动 PG/Redis。收集阶段仍会导入模块/conftest，须使用项目测试环境；本脚本不是隔离沙箱。

CI 将此命令作为独立步骤即可：退出 0 代表收集检查通过，退出 1 表示错误或数量不足，退出 2 表示参数无效。输出一行 `COLLECTION_GUARD {JSON}`，也可通过 `--output` 保存同一 JSON 供构件归档。未修改现有 CI workflow。

通过条件同时满足：pytest 原生退出码为 0、收集失败节点数为 0、用例数至少为下限。默认下限 1350 来自 T-T35 历史证据，只作防缩量下限，不代表今天恰有 1350 条，也不代表业务测试通过。真实 CI 基线增长后可显式提高：

```powershell
python tests/tools/check_collection.py --min-collected 1600 --output collection-summary.json
```

`skipped_collectors` 单独记录模块 skip，绝不将其写作通过的业务测试。忽略调用环境的 `PYTEST_ADDOPTS` 与配置中的 `addopts`，固定 strict-config、strict-markers、importlib 和禁用 pytest 缓存，避免继承 `-k`/`-m` 等筛选导致悄悄漏收集。配置中 testpaths、忽略目录或第三方 hook 仍应由 CI 评审，计数下限不是逐节点清单替代。

定点自检（全部临时合成目录、无真实数据）：

```powershell
python -m pytest tests/tools/test_check_collection.py -q -p no:cacheprovider
python tests/tools/check_collection.py --min-collected 10 tests/tools
```

仅为自检可指定根内路径和更小下限；整树 CI 使用默认 `tests`。不存在路径、根外路径、非正下限均拒绝。`MAIRUI_MODE=replay`、`MAIRUI_LICENCE` 置空在导入测试前设置，不读取凭据文件；不在含敏感原始数据的目录上使用本工具。

冻结 `3d7504d` / main 基线 `465e020` 的本地实测：脚本自检 10 passed；真实整树 1596 collected / 4 errors，正确退出 1。未修改基线为 1586 collected / 同样 4 errors；新增 10 项来自本脚本自检。四个错误为 schemathesis、hypothesis、requests 缺依赖和 milestone 的 tt21_head 裸导入；不以脚本交付宣称整树已零错，不在本单跳过它们。
