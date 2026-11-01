# ashare-invest-assistant

A 股个人投资研究与决策助手。架构方案见 [`docs/plan.md`](docs/plan.md)，REST 契约见 [`docs/api-contract.md`](docs/api-contract.md)。

## 本地一键启动（Phase 0 骨架）

```bash
deploy/scripts/up.sh          # 首次会从 deploy/env/.env.example 生成 deploy/env/.env
deploy/scripts/compose.sh ps  # 查看状态
deploy/scripts/down.sh -v     # 停止并删除数据卷
```

- 需要 Docker Engine + compose v2 插件。非 systemd 主机上 `up.sh` 会调用 `deploy/scripts/start-dockerd.sh` 拉起 dockerd。
- 本地默认叠加 `deploy/compose/docker-compose.dev.yml`：**麦蕊回放模式**（`MAIRUI_MODE=replay`，`ingest` 中 licence 强制为空）。
- `MAIRUI_LICENCE` 只注入 `ingest` 容器（plan §2.1A）；任何 `.env`、证书、真实交割单都不入库（见 `.gitignore`）。
- 业务服务目前是占位健康检查入口，业务代码由后续任务（T-B01 起）实现。
