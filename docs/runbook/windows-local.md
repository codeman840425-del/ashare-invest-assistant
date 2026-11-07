# Windows 本地部署（WSL Ubuntu）

来源：T-A10；部署入口：`deploy/scripts/up.sh`、`deploy/scripts/compose.sh`。
仓库目前没有 `docs/runbook/` 既有文档；本页沿用 `deploy/runbooks/` 的分节、命令块与权限表风格。

## 1. 运行环境与换行

部署脚本是 bash，必须在 **WSL Ubuntu** 中运行，不要直接在 PowerShell 或 CMD 执行。
先准备 WSL 内可访问的 Docker 与 Compose；本页不操作 Docker daemon。
以下命令均在 WSL 的仓库根目录执行。建议使用 WSL Linux 文件系统中的工作树。

```bash
git config core.autocrlf false
```

这是本仓库的配置，不是全局配置。CRLF 会导致 bash 的解释器路径、参数或语法解析报错；脚本须保持 LF。
该设置不会自动修复已经变成 CRLF 的文件；已有工作树需先检查换行，避免覆盖未提交改动。

## 2. 密钥目录与权限

本机约定将密钥放在 **WSL 的 `/root/.config/aia/secrets/` 下**，不放 Windows 目录或仓库内。
使用 WSL root 用户管理该目录；普通用户不能默认穿过 `/root` 访问它。
在 `deploy/env/.env` 中明确设置 `AIA_SECRETS_DIR` 为 `/root/.config/aia/secrets/<数据卷前缀>`
（尖括号部分替换为本部署的实际卷前缀，不是密钥值）。配置文件本身保持 600。
脚本默认其实是 `${XDG_CONFIG_HOME:-$HOME/.config}/aia/secrets/<数据卷前缀>`，
因此非 root 用户不能假定默认路径就是 `/root`；shell 导出的同名变量也不会覆盖该配置。
目录权限为 700；密钥跟随数据卷，切换工作树不得随意换钥。

| 文件名（相对于 AIA_SECRETS_DIR） | 权限 / 属主约定 |
|---|---|
| `data_licence_seal_private_keys` | 600 / 容器用户 10001 |
| `data_licence_seal_public_keys` | 644 |
| `data_licence_seal_keys.meta.json` | 644 |
| `db_password_aia_api`、`db_password_aia_ingest` | 600 |
| `db_password_aia_maint`、`app_master_key` | 600 / 容器用户 10001 |

不打印、不粘贴、不提交任何密钥或证书值。密钥备份与数据库备份分开存放。
完整生成、恢复和属主要求见 [证书封装密钥手册](../../deploy/runbooks/data-licence-seal-keys.md)
与 [数据库手册](../../deploy/runbooks/database.md)。已有数据卷缺私钥时必须恢复原钥，不得用新钥替代。

## 3. 启动与排查

以下为操作说明，本任务未执行启动。运行前先确认 Docker 已可用：`up.sh` 在特定非 systemd 环境下可能自动启动 daemon。
默认 `dev` profile 使用麦蕊回放；本页不切换 live，不调用麦蕊接口。

```bash
bash deploy/scripts/compose.sh --resolve
bash deploy/scripts/up.sh
bash deploy/scripts/compose.sh ps -a
bash deploy/scripts/compose.sh logs migrate timescale-apply
```

`compose.sh` 缺少 `deploy/env/.env` 时从 `.env.example` 生成配置；先核对配置再启动。
`up.sh` 默认构建镜像，执行迁移与策略初始化，等待服务健康；已有数据卷缺封装密钥时会停止。

## 4. 待补项（不代表已可用）

- **前端构建与 nginx 接入：待补，运维 T-O19 负责。** 本页暂不承诺浏览器入口或完整前端可用。
- **create-admin 命令：尚未实现，待补，后端 T-B64 负责。** plan 中提到的命令是目标接口，当前不要作为可执行步骤；实现并验收后再补首个管理员创建流程。
