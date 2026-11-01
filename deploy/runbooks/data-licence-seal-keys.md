# 证书封装密钥（data licence seal keys）运维手册

来源：T-A07 §2/§5、plan §2.1B；实现：T-O09。

用户在网页“设置 → 数据证书”录入的麦蕊证书，由 api 用 **HPKE Base 模式**
（DHKEM(X25519, HKDF-SHA256) + HKDF-SHA256 + AES-256-GCM，RFC 9180）加密后存库，
AAD = `mairui-licence|v1|<user_id>|<row_id>|<key_version>`。只有 ingest 持有私钥、能解密。
部署配置里**不再有全站麦蕊证书变量**；ingest 发现该变量非空会拒绝启动（后端实现，T-B04a/T-B45）。

> **备份提醒：私钥丢失 = 库里所有已加密的证书永远无法解密**（用户只能重新录入）。
> 私钥必须单独备份，且**不能**和数据库备份放在同一位置/同一介质：两者放一起，偷到一份备份就能解出全部证书。

## 1. 文件与位置

| 文件 | 权限 / 属主 | 挂给谁（docker secret，只读） | 入库？ |
|---|---|---|---|
| `data_licence_seal_private_keys` | 600 / 10001（容器用户） | 只有 ingest：`/run/secrets/data_licence_seal_private_keys` | **永不** |
| `data_licence_seal_public_keys` | 644 | api、ingest（轮换时 ingest 要重新封装） | 不入库（和本机部署绑定） |
| `data_licence_seal_keys.meta.json` | 644 | 不挂 | 不入库（只有版本、时间、公钥指纹） |

- 目录 `AIA_SECRETS_DIR`：`deploy/env/.env` 里设置 > 缺省 `~/.config/aia/secrets/<数据卷前缀>`（目录 700，在仓库外）。
  按数据卷前缀区分，密钥跟着它加密的那份数据走；`deploy/scripts/compose.sh --get AIA_SECRETS_DIR` 打印解析结果。
  shell 里导出的同名变量不生效（同 COMPOSE_PROJECT_NAME 的规则）。
- 文件格式：单行 JSON `{"<key_version>": "<base64 DER>"}`；私钥 PKCS#8 DER（48 字节），公钥 SPKI DER（44 字节）。
  可以同时有多个版本（轮换期间）。当前加密版本：环境变量 `DATA_LICENCE_SEAL_KEY_VERSION`（api、ingest）。
- 后端加载：pydantic-settings `secrets_dir=/run/secrets`，设置项 `DATA_LICENCE_SEAL_PRIVATE_KEYS` / `DATA_LICENCE_SEAL_PUBLIC_KEYS`。
- 为什么改属主：非 swarm 的 compose file secret 是只读绑定挂载，`uid/gid/mode` 不生效；容器以 uid 10001 运行，
  600 且属主为宿主机用户的文件在容器里读不到。所以私钥属主改为 10001、权限仍是 600。宿主机上查看需 `sudo`。
- 防误提交：`.gitignore`（`data_licence_seal_*`、`*_private_keys*`、`deploy/secrets/`）；
  密钥扫描 S3 规则 `S3-x25519-pkcs8`（私钥内容）、`S3-seal-private-key-file`（私钥文件名），
  S4 把 `DATA_LICENCE_SEAL_PRIVATE_KEYS` 列为 .env.example 敏感键；CI job `secret-boundary` 检查私钥只给 ingest。

## 2. 首次生成

```bash
deploy/scripts/seal-keygen.sh            # 版本 1，写到 AIA_SECRETS_DIR；已有文件则不覆盖、直接退出
```

`up.sh` 在密钥缺失时：若本卷前缀的 `<前缀>_pgdata` 卷还不存在（全新部署）会自动调用它；
若数据卷已存在则**停止**——库里可能已有用旧私钥加密的证书，换新密钥会让它们永远解不开，必须先从备份恢复私钥。

生成后立刻备份私钥（见 §3）。脚本只打印路径与公钥指纹，从不打印密钥。

## 3. 备份与恢复

- 备份：`sudo cat <目录>/data_licence_seal_private_keys`，用独立口令加密后放到**与数据库备份不同**的位置
  （例如离线介质/密码管理器），同时记下 meta.json 里的版本与公钥指纹，便于核对。
- 恢复：把文件放回 `AIA_SECRETS_DIR`，`chmod 600`，`sudo chown 10001:10001`；公钥可由私钥重新导出。
- 数据库备份（`deploy/scripts/db-backup.sh`）**不含**私钥；在开发机恢复生产备份时没有私钥，证书解不开——这是预期行为。

## 4. 轮换（新密钥 → api 切版本 → ingest 逐行重新封装 → 退役旧私钥）

1. 在临时目录生成新版本：`deploy/scripts/seal-keygen.sh --version N --dir /tmp/sealN`（不会碰现有文件）。
2. 把新版本合并进现有两个 JSON 文件（私钥文件需 `sudo`；合并后私钥仍 600/10001），**不要删旧版本**；删除临时目录。
3. 在 `.env` 设 `DATA_LICENCE_SEAL_KEY_VERSION=N`，用 `deploy/scripts/compose.sh up -d api ingest` 重建这两个服务
   （secret 内容在容器创建时挂载，改文件后要重建容器才生效）。此后新录入的证书用版本 N 加密。
4. ingest 逐行把旧版本密文解密、用版本 N 重新封装（后端提供的重新封装任务）；确认库里已没有旧版本密文。
5. 从私钥文件里删掉旧版本，重建 ingest；更新私钥备份，旧私钥备份按保留策略销毁。

## 5. 冷备切换

冷备主机接管时必须**同时带上私钥**（以及公钥、`DATA_LICENCE_SEAL_KEY_VERSION`）。只恢复数据库不带私钥，
所有证书都解不开、行情采集全部停摆。切换演练清单里要包含“私钥已在冷备主机就位并能被 ingest 读取”。

## 6. 本地 shell 里的麦蕊证书变量

本机实测时可以在本地 shell 临时设置真实证书（例如 `check_real_secrets.sh` 从环境变量读取它做精确比对）；
compose 不再把它传进任何容器，所以本地容器拿不到它。
