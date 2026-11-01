# ashare-invest-assistant

A 股个人投资研究与决策助手。架构方案见 [`docs/plan.md`](docs/plan.md)，REST 契约见 [`docs/api-contract.md`](docs/api-contract.md)。

## 本地一键启动（Phase 0 骨架）

```bash
deploy/scripts/up.sh          # 首次会从 deploy/env/.env.example 生成 deploy/env/.env
deploy/scripts/compose.sh ps  # 查看状态
deploy/scripts/down.sh -v     # 停止并删除数据卷
```

- 需要 Docker Engine + compose v2 插件。非 systemd 主机上 `up.sh` 会调用 `deploy/scripts/start-dockerd.sh` 拉起 dockerd。
- 本地默认叠加 `deploy/compose/docker-compose.dev.yml`：**麦蕊回放模式**（`MAIRUI_MODE=replay`，不调用麦蕊）。部署配置不再有全站麦蕊证书变量；`ingest` 发现 `MAIRUI_LICENCE` 非空会拒绝启动。证书由每位用户在“设置 → 数据证书”中录入，加密后入库（plan §2.1B，契约 v0.2.6）。
- 证书封装密钥以 docker secret 交付（私钥只挂 `ingest`，公钥挂 `api` 和 `ingest`），存放在仓库外的 `AIA_SECRETS_DIR`，见 `deploy/runbooks/data-licence-seal-keys.md`；任何 `.env`、证书、私钥、真实交割单都不入库（见 `.gitignore`）。
- 业务服务目前是占位健康检查入口，业务代码由后续任务（T-B01 起）实现。
