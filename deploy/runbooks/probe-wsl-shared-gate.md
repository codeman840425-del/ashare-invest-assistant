# 探针 WSL 共享门禁运行接线（T-O44，路径 A）

北京时间 2026-11-09 接线。适用 T-B05/T-B86 真实探针与产品 ingest 共享 fail-closed 门禁（T-A53/T-B99e）。
本 runbook 只覆盖环境与接线；真实执行、解闩、证书接入仍须 Chief 当次派单。

## 共享面（唯一物理目录，禁止副本/软链/Windows 目录替代）

- 路径：WSL Ubuntu 原生 ext4 `/var/lib/aia-shared-gate`（0700，属主 aia:aia = uid/gid **10001**）。
- 产品侧：ingest 容器 bind 挂载同一路径，`MAIRUI_SHARED_STATE_DIR=/var/lib/aia-shared-gate`（compose 默认，可用 `AIA_SHARED_GATE_HOST_DIR` 改宿主源）。
- 探针侧：WSL 本机 Python 以 **aia（uid 10001）** 运行（与容器 ingest 同一受控 UID，T-B99e 硬性要求；root 或其他用户写的 0600 文件对侧读不了）。
- 不可用方案（已实测否决）：Windows DrvFs 路径直挂（/mnt/f 权限位 777，过不了 `st_mode&0o007` 私有性检查）；Windows 探针经 `\\wsl$` UNC（9p 会话映射 uid1000，目录 700/10001 读写被拒）。

## 探针执行环境（已验证）

- WSL Ubuntu `/usr/bin/python3` = Python 3.12.3；venv `/opt/aia-probe-venv`（root 建，aia 只读执行）。
- 依赖：`cd /mnt/f/wt-backend-T-B99e/src/backend && UV_PROJECT_ENVIRONMENT=/opt/aia-probe-venv uv sync --frozen --no-dev --no-install-project`（uv 已装在该 venv 内），另 `pip install requests`（后端不依赖 requests，探针另需）。
- 已验证版本：requests 2.34.2 / SQLAlchemy 2.1.6 / psycopg 3.3.6；`app.ingest.shared_gate` / `certificate_bindings` / `send_control` 导入通过。
- `/home/aia`（0700，aia:aia）已建，供 T-B86 台账等 aia 可写路径；台账具体位置按当次派单。

## 探针执行命令口径（13:00 触点；占位符由当次派单填）

```bash
wsl -u root -e bash -lc 'runuser -u aia -- env \
  PYTHONPATH=/mnt/f/wt-backend-T-B99e/src/backend \
  MAIRUI_SHARED_STATE_DIR=/var/lib/aia-shared-gate \
  /opt/aia-probe-venv/bin/python /mnt/f/wt-backend-T-B99e/src/backend/probes/run_all.py <当次参数>'
```

- 证书：`MAIRUI_LICENCE` 只按当次授权在进程内注入（WSLENV 或 `read -rs`），不入命令行/日志/文件。
- `MAIRUI_SHARED_DATABASE_URL_FILE`（T-B99e 探针 DB 参考，0400 私有 DSN 文件）：由当次派单提供，运维不生成真实 DSN；缺失时探针应闭锁而不是退回本机时钟。
- `policy.json`、证书绑定：产品侧写、探针只读；运维不造 policy 数据。
- 出口 IP：探针在 WSL 跑与 Windows 本机同一台机器同一出口，口径不变；不碰 a-stock-assistant-v2；replay 不变。
- 离线自检（不出网）：同一命令加 `--dry-run` 即可，不需真实证书。

## 双向互见验证（T-O44 已做，方法可复用）

两侧各用 `shared_gate._write`（0600 独占创建）/ `_read`（regular+nlink=1+权限位检查）/ `stop_present` 对临时测试文件验证：
WSL 探针写→容器读过检；容器写→WSL 探针读过检。测试文件用后删除；**不得为验证写真 STOP/PAUSED**。

## 运维边界

- 不触真 STOP/PAUSED/policy.json；不解闩、不删台账；不替后端决定探针参数。
- ingest recreate 仅应用挂载与环境变量，MAIRUI_MODE 保持 replay，不外呼。
