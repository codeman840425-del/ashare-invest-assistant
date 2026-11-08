# 评审 2d46332（评审 8cf9771 后续：M1 / m1 / m2 / m3 / n1–n5）

- 评审人：架构师；日期：2026-11-01（America/Denver）
- 方法：`git archive` 干净导出到 /tmp/rv/2d46332（git init 后跑测试）；不读、不打印任何真实密钥，实验只用随机生成的假值；未调用麦蕊。
- 自检：`scripts/ci` 全量 pytest（AIA_CI_REQUIRE_DOCKER=1，真实 gitleaks）533 passed / 5 failed / 0 skipped。5 个失败都在 `test_secret_scan.py`（allowlist / history），父提交 ab84776 同一导出方式下同样失败，原因是单个导出提交的历史里含 `.secretscan-allow.yaml`，属环境问题，不是本提交回归。`test_app_master_key_ensure_pg.py` 的真实 PG 用例实际执行（未 skip）。shellcheck（koalaman/shellcheck:stable，warning 级）只有 SC1111（中文引号）误报。

## 结论：**可以推送**（无 B / M）

## 1. 原评审项逐条核对

| 项 | 要求 | 结果 |
|---|---|---|
| M1 | 迁移流程第 2 步不得启动 ingest | ✅ `deploy/runbooks/database.md:95-122`：① 拷主密钥并核对 sha256 → ② `compose.sh up -d --wait --scale ingest=0`，且之后每次 up 都带该参数 → ③ db-restore、恢复导入卷 → ④ 核对 → ⑤ 按 plan §1.3 切换 ingest（停旧 → 等 ≥60 s → `up -d --wait ingest` → 核对出口 IP → 删除旧主机 licence）。核对：没有服务 `depends_on: ingest`，ingest `deploy.replicas: 1`、无 profiles，`--scale ingest=0` 确实不起；顺序与 plan.md §1.3 迁移流程一致。灾后恢复（旧主机已不在）可直接起 ingest，合理。 |
| m1 | 先解析后判占位 | ✅ 随机假值实测：行尾注释含 `<docs>` / `->` 且与 secret 不一致 → rc=3；一致 → rc=0；占位值 → rc=0；非法写法的真实值 → rc=3；输出中出现假值 0 次。 |
| m2 | 密钥定义不可改道 | ✅ 下列写法全部被 `check_secret_boundary.py` 拦下：别名 secret 指向 app_master_key 再挂给 ingest；别名指向 seal 私钥再挂给 api；override 改 secret 路径；configs；driver_opts；include；长格式 source 挂给 ingest；environment 来源 secret；base 路径 `../` 穿越；extends.file；同文件 extends 派生未登记服务。 |
| m3 | 关 xtrace | ✅ `env SHELLOPTS=xtrace` 与 `bash -x` 下运行 ensure：假值泄露 0、`+` 开头行 0；`sh -x` 下 secret-env.sh 泄露 0。 |
| n1 | compose.sh 子命令白名单 | ✅ `deploy/scripts/compose.sh:143` 只读 / 停止类子命令放行，其余（含 up / run / start / restart / create）一律先跑 ensure。 |
| n2 | 真实 PG 用例 | ✅ 有 Docker 时实际执行。 |
| n3–n5 | runbook 补充 | ✅ 已写入 database.md。 |

主密钥范围复核（安全重点）：`deploy/compose/docker-compose.yml` 只有 api、worker 挂 `app_master_key`；ingest 设 `AIA_FORBID_APP_MASTER_KEY=1`，`deploy/scripts/secret-env.sh:17-19` 发现环境变量或 `/run/secrets/app_master_key` 即 exit 2；后端 `app/workers/ingest.py:42-52`（exit 78）与 `config.py` `MASTER_KEY_FORBIDDEN_SERVICES` 也拒绝。迁移顺序“先拷 app_master_key 再 up”成立。

## 2. 新发现

- **m1** `deploy/runbooks/database.md:80`：导入卷备份命令注释写“产物 chmod 600”，但命令里没有 chmod；容器内 root、默认 umask 产出的是 root 属主 644 文件。修复：命令后加 `&& chmod 600 /out/imports-<UTC>.tgz`（或 `umask 077 &&` 前缀），并在核对步骤里 `stat -c %a` 确认。
- **n1** `deploy/runbooks/database.md:96`：迁移第 1 步仍是手工拷贝 + 比摘要；b195ca6 已有 `app-master-key-backup.sh restore`，应改为指向脚本并以台账 sha256 为准（见 review-b195ca6 M1）。
- **n2** `check_secret_boundary.py` 仍挡不住两种写法：`file: ${MKFILE}` 用其他变量间接指定路径；ingest 挂载上级目录（如 `${HOME}/.config/aia`）。只能靠人工评审；建议后续规则：secret `file:` 只允许字面量 `${AIA_SECRETS_DIR}/<名>`，ingest 的 volumes 不得包含 `AIA_SECRETS_DIR` 或其上级。
- **n3** “之后每次 up 都带 `--scale ingest=0`”靠人记；可考虑 compose.sh 识别迁移标记文件时自动附加。非必须。

---
裁定登记：docs/plan.md 本地提交 1294476（未推送）——A 网关 `proxy_connect_timeout 3s`（运维）；B 主密钥多版本为上线门槛，新增后端任务 **T-B57**，重加密 CLI / 轮换流程放 V2（运维在 T-O12 之后跟进），契约不变；§9 问题 95（默认执行，用户可改，上线推迟一个后端任务的工作量）。
