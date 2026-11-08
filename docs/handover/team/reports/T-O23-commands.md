# T-O23 测试复验 13 项：准备好的命令（运维只准备，没有执行；由测试角色执行）
基线：本地 main e9536e2（含 runner）。复验对象沿用 T-T20 的只读导出，或测试角色自己的只读导出，不要 checkout 共享 main。
宿主上的只读输入：
- Git 对象库：/workspace/ashare-invest-assistant/.git → 只读挂到 /git-ro（run.sh 和 git-ro.sh 会拒绝可写挂载）；要能解析 3895963f5366d734e5229b210b92d6811851fc62:docs/strategies/feature_spec.md
- Python：<path> → 只读挂到 /hostpy
- uv 离线缓存：<path> → 只读挂到 /cache
- 代码：只读导出目录 → /code；testkit：/code/deploy/testkit/tt20（或单独只读挂载）
1. 构建镜像（需要联网拉 debian:bookworm-slim 并 apt 装 git；本机没有这个镜像，也没构建过）：
   docker build -t aia-tt20-runner:e9536e2 deploy/testkit/tt20
2. 探针（不跑 pytest），用 --network none，只挂上面这些只读目录，再加一个可写的 /tmp：
   docker run --rm --network none --read-only --tmpfs /tmp -v <导出>:/code:ro -v /workspace/ashare-invest-assistant/.gi<path> -v <path> -v <path> aia-tt20-runner:e9536e2 sh -c 'sh /code/deploy/testkit/tt20/materialize-offline-venv.sh && sh /code/deploy/testkit/tt20/run.sh --check'
   预期输出“git 对象只读可读，alembic 可被子进程继承”。
3. 定点复验 13 项：同上容器，materialize 之后执行
   . /code/deploy/testkit/tt20/export-pythonpath.sh && cd /code && /hostpy/bin/python3.12 -m pytest -p no:cacheprovider -c tests/pytest.ini src/backend/selfchecks/test_ta13_feature_metadata.py src/backend/selfchecks/test_tr18_sources.py "src/backend/selfchecks/test_ta14_migrations.py::test_exact_single_head_and_paused_file_unchanged" -q --tb=short
   - 预期：ta13 收集 1 项 + tr18 的 11 项 + ta14 的 1 项。tr18 需要数据库夹具时，按 T-T20 的方式挂测试角色自己隔离的 PG socket，不要用共享库；
   - 正式卡审计钩子按 T-T20 的 run_cached.py 原样使用。
注意：
- run.sh 不加参数时拒绝运行；TT20_RUN_PYTEST=1 会跑全量 pytest，不是只跑这 13 项，定点复验请用第 3 步；
- materialize 在只读 /cache 上做 uv 离线同步，能不能成功本机没在 Docker 里验证过；失败就停下，报给运维或 cloud，不要改成联网安装。
