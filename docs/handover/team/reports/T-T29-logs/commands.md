# T-T29 原始证据与命令（北京时间 2026-11-09）
- 冻结 SHA：251b4cb76361d43ade4f382500cbde5c7340c8dc（main=origin/main，工作树干净）；以下全部来自该 SHA 的定点复跑，未跑全量、未改动业务代码。
- 环境：临时 venv `.venv-tt29`（Python 3.13.11，pytest 9.2.0），`PYTHONPATH=src/backend`，`PYTHONUTF8=1`，TEMP/TMP 指向可写目录；Docker npipe 权限拒绝，未起任何容器。
- 命令模板：`python -m pytest -c tests/pytest.ini -p no:cacheprovider -q --tb=line <files>`。
- api_app 整目录：`... -v --tb=no tests/backend/api_app` → 2 failed / 380 passed / 397 skipped / 9 xfailed，37.11s（api_app-summary.txt）。
- TB72+配置清单：`... src/backend/selfchecks/test_tb72_features.py tests/backend/api_app/test_config_yaml_defaults.py` → 10 failed / 67 passed / 3 xfailed（tb72-config-defaults.txt）。
- CONFIG_DIR 模拟：`AIA_CONFIG_DIR=<repo>/tests/backend/api_app/config_defaults` 跑 test_config_yaml_defaults.py → 3 errors（FileNotFoundError: share_class_list）+ 1 failed（api_app-configdir-sim.txt）。
- selfchecks 设施类：两批共 16 文件 → 173 errors / 226 passed / 7 failed（selfchecks-facility.txt）；全部为 /tmp POSIX socket 与 Windows/psycopg 平台问题。
- 收集错误 5 个：schemathesis 未安装、test_tt21_migrations 缺 `-p tt21_plugin`/`tt21_head` 路径、fcntl 两处（Windows）、test_tb71_import 外部命令 WinError 2。
- 限制：旧 `T-T22-closeout-logs/failures.md` 未入库，T-T22 的 15 败无法按 nodeid 逐条复核；本报告不把 18 项新复核结果等同于旧 15 项。
