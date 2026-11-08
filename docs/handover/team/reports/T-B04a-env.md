# T-B04a-env ingest 拒绝 MAIRUI_LICENCE（契约 v0.2.6 / T-A07 §5 / plan §2.1B 第 7 点）

- 作者：后端；日期：2026-11-02；提交：bc0b3d8（只在本地，未推送）
- 范围：src/backend/app/workers/ingest.py、src/backend/app/config.py（只改应用代码；**src/backend/probes/ 未动**，今晚实测仍从本机环境读取）

## 改动
- `ingest.main()` 在读取配置、连接 Redis 之前检查：环境变量 `MAIRUI_LICENCE` 去首尾空白后非空 → 向 stderr 输出固定说明（只含变量名，不含值、长度或片段），退出码 **78**（EX_CONFIG）。空白或未设置照常启动。
- 判断函数 `legacy_licence_present()` 只返回布尔值；代码中没有任何读取该值后再使用的路径。
- `config.py` 模块说明同步：本服务不读取 `MAIRUI_LICENCE`，生产改为每用户 HPKE 密文存库，只有 ingest 持有私钥。

## 验证（只用运行时生成的假值）
- /tmp/tb02/selftest_env.py 7/7：非空/空白/未设置三种判定；子进程退出码 78；输出不含假值任意 4 字符子串；只提变量名。
- 未设置与空白时进程照常运行（timeout 4 s 结束，退出码 124）。
- ruff / ruff format / mypy 通过；测试套件与提交前相同（501 passed，3 个失败均为 v0.2.6 文档先行引起，见 T-B16b 报告）。

## 需要他人
- 运维（T-O09）：compose 与 `.env.example` 已不再给容器注入 `MAIRUI_LICENCE`（工作区中运维未提交的改动）；**部署前务必确认 ingest 容器环境里没有它，否则 ingest 会拒绝启动**（这是预期行为）。
