# 评审 b195ca6（T-O12 主密钥离线备份 / 核对 / 恢复脚本；V1 不轮换，裁定 ⑤）

- 评审人：架构师；日期：2026-11-01（America/Denver）
- 方法：干净导出到 /tmp/rv/b195ca6；随机假钥实验，不接触真实密钥；未调用麦蕊。
- 自检：`scripts/ci` 全量 568 passed / 5 failed（同 2d46332 说明，test_secret_scan 导出环境问题，父提交同样失败）；新增 `scripts/ci/tests/test_app_master_key_backup.py` 12 例通过。shellcheck：SC2155（第 110 行）一条，其余 SC1111 误报。

## 结论：**可以推送**；但 **M1 修好之前，restore 不得作为正式迁移 / 灾后恢复流程使用**（runbook 仍以“台账 sha256 人工比对”为准）

## 1. 安全要点核对（逐项实测）

| 要求 | 结果 |
|---|---|
| 不把密钥打到日志 / stdout | ✅ `deploy/scripts/app-master-key-backup.sh:12` `{ set +x; } 2>/dev/null`；值只经管道；xtrace 下 backup / verify 输出中假值出现 0 次 |
| 临时文件 0600 且清理 | ✅ `umask 077`，tmp 600，`trap … EXIT` 清理；实测 SIGTERM / SIGHUP 下 EXIT trap 执行、无残留；SIGKILL 会残留 600 文件（无法避免，可接受） |
| 不覆盖已有文件 | ✅ backup 用 `ln` 落盘不覆盖；restore 目标已存在即拒绝，`mv -n` |
| 恢复前先核对指纹 | ⚠ 有 `.sha256` 时核对；**缺 `.sha256` 只警告并继续**（见 M1） |
| 不轮换 | ✅ `rotate` 返回 2 |
| 与 ensure 不冲突 | ✅ `compose.sh --get` 在第 86 行提前返回，不会触发 ensure 生成新钥 |

## 2. 问题

- **M1** `deploy/scripts/app-master-key-backup.sh:91-92`：restore 时备份旁没有 `.sha256` → 只打印警告并恢复（实测 rc=0）；把备份文件与 `.sha256` 一起替换成另一把钥也能恢复（实测 rc=0）——核对的只是“备份自洽”，没有与运维台账比对。修复：增加 `--expect-sha256 <台账值>`；有它时必须与之相等；没有 `.sha256` 时必须提供该参数，否则拒绝（非零退出、不写目标）；runbook 迁移第 1 步改为用此参数。
- **m1** `app-master-key-backup.sh:97-101`：`chown 10001` 失败只警告，仍写入并返回 0，结果是 api/worker 读不到 secret、启动失败才发现。修复：chown 失败即清理临时文件并非零退出。
- **m2** `app-master-key-backup.sh:57-60`：`--dest` 只与密钥目录做相等比较，是其子目录也允许备份（实测 rc=0）；dump 检查只看顶层，dump 放在子目录里也允许（实测 rc=0）。修复：用 `realpath` 后做前缀判断（dest 不得在密钥目录内、也不得与任何 `*.dump`/pg_dump 产物同目录或子目录）。
- **n1** `app-master-key-backup.sh:58`：`mkdir -p "$dest"` 在第 65 行 `umask 077` 之前，新建目录 755。把 umask 提前或 `mkdir -m 700`。
- **n2** `app-master-key-backup.sh:22-25` `abs_outside_repo` 用逻辑路径，可被符号链接绕过；改 `realpath`。
- **n3** `app-master-key-backup.sh:110` SC2155（declare 与赋值分开）。

## 3. 与 V2 / 裁定 B 的关系

T-O12.md §2 的轮换方案保留为 V2。架构师裁定 B（以用户 steering 为准）：**主密钥多版本改为上线门槛**，由后端新任务 **T-B57** 完成最小集（加密列 / 密文带 kek_id、HMAC 列带 key_id；多钥密钥环；多钥 secret 文件并标当前钥；自检）；后台重加密 CLI 与运维轮换流程仍是上线后 V2，运维在 T-O12 之后跟进；契约不变；plan §9 问题 95（默认执行，用户可改，上线推迟一个后端任务的工作量）。
运维随 T-B57 的配合项：主密钥文件格式变为多钥后，ensure（是否真实值 / 长度校验）与本脚本的 sha256 台账要按“整文件”或“按 id”重新定义，需与后端约定格式后同步改。

---
裁定登记：docs/plan.md 本地提交 1294476（未推送）——A 网关 `proxy_connect_timeout 3s`（运维）；B 主密钥多版本为上线门槛，新增后端任务 **T-B57**，重加密 CLI / 轮换流程放 V2（运维在 T-O12 之后跟进），契约不变；§9 问题 95（默认执行，用户可改，上线推迟一个后端任务的工作量）。
