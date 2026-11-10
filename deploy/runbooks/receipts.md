# 授权收据卷（T-O68 L-5 / T-O66b）

ingest 与 worker 把 `<前缀>_aia_receipts` **只读**挂到 `/run/aia/receipts/`。卷根与其中文件须为 **root 所有**（容器用户 10001 只能读，不能改或删）。本手册只讲怎么把收据文件装进去；**装入或删除收据都不能当作恢复麦蕊出口的手段**，见文末。

前缀与 `deploy/scripts/compose.sh --get AIA_VOLUME_PREFIX` 一致（只认 `deploy/env/.env`，不认 shell）。

## 用一次性 root 容器写入

不要 `exec` 进正在跑的 ingest/worker 去写（它们是 :ro，且非 root）。起一个用完即删的临时容器，以 uid 0 挂上同一具名卷：

```bash
prefix="$(deploy/scripts/compose.sh --get AIA_VOLUME_PREFIX)"
# 虚构示例内容；真实收据由授权流程产生，不要把证书明文写进手册或提交进仓库。
docker run --rm --network none --user 0 \
  -v "${prefix}_aia_receipts:/run/aia/receipts" \
  alpine:3.21@sha256:bc21487101ae47172509130ee1092cc273a831968d64b617776d1f69c81e42ab \
  sh -c 'set -e
    install -d -o root -g root -m 0755 /run/aia/receipts
    cat > /run/aia/receipts/mairui-daily.json <<EOF
{"kind":"authorization-receipt","note":"fictional-example-not-a-licence"}
EOF
    chown root:root /run/aia/receipts/mairui-daily.json
    chmod 0644 /run/aia/receipts/mairui-daily.json
  '
```

校验（仍用一次性 root 容器，避免改挂载模式）：

```bash
prefix="$(deploy/scripts/compose.sh --get AIA_VOLUME_PREFIX)"
docker run --rm --network none --user 0 \
  -v "${prefix}_aia_receipts:/run/aia/receipts:ro" \
  alpine:3.21@sha256:bc21487101ae47172509130ee1092cc273a831968d64b617776d1f69c81e42ab \
  sh -c 'set -e
    echo "dir $(stat -c "%U:%G %a %n" /run/aia/receipts)"
    echo "file $(stat -c "%U:%G %a %n" /run/aia/receipts/mairui-daily.json)"
    # 期望：目录 root:root 755；文件 root:root 644。ingest/worker 以 10001 只读打开即可。
  '
```

也可以从已启动的栈里只读查看（不能写入）：

```bash
deploy/scripts/compose.sh exec ingest ls -la /run/aia/receipts
```

临时容器不要加 `aia_egress`，不要调麦蕊。验完若只是练习写入，删掉练习文件即可，**不要**删除整个数据卷，也不要 `down -v`。

## 只删收据文件不能恢复出口

权威来源是**数据库**里的停机状态（如 `upstream_halted`、`ops.data_licence_events` 中 ingest 写入的限流暂停），以及本机停机标志 `/run/aia/state/halt/`（见 `ingest-halt.md`）。收据卷只是授权材料的只读副本。

因此：

- 只删 `/run/aia/receipts/` 下的文件、甚至换一只空的收据卷，**不会**让 ingest 恢复出网。
- 只删停机标志文件同样不够：库一侧的暂停仍在；`ingest-halt.md` 写明「文件丢了也照样停」，解除必须先核对库侧条件，并**由用户本人确认**后再删本机标志。不要手工清理 `ops.data_licence_events`（`database.md` §6.1）。

## 主数据首次导入的一次性出网（编排者裁定 ④，2026-11-09）

`maint-cli` 与默认栈**平时不出网**。主数据首导若要联网拉上交所/深交所/北交所官网的公开 HTTPS 名单，只通过 `deploy/scripts/master-bootstrap.sh` 启动 opt-in 服务（加入 `aia_egress`），以保留 `--check`、flock、`--confirm-network-fetch` 和 CI 拒绝。不要 `compose.sh --profile master-bootstrap run …`。走法与 `wrapup-deploy.md` / `master-data.md`「主数据首次导入与词表」相同，不得分歧：先 `--check`；**其它 rc 一律停止**。`--run` 路径跑完容器即删、不常驻、**不调麦蕊**。

```bash
deploy/scripts/master-bootstrap.sh --check; echo "rc=$?"
# rc=10：确认本机可访问上交所、深交所、北交所官网后
deploy/scripts/master-bootstrap.sh --run --confirm-network-fetch --rebuild-search-terms
# rc=0：已有成功导入，不要再 --run；在不出网 worker 上跑离线 CLI（先 dry-run 再 --apply；不要用 maint-cli）
deploy/scripts/compose.sh run --rm --no-deps -T --entrypoint python worker -m app.cli.security_search_terms
deploy/scripts/compose.sh run --rm --no-deps -T --entrypoint python worker -m app.cli.security_search_terms --apply
```

不要把该 profile 写进默认 `up.sh` / `AIA_PROFILE=dev|live`。worker 上的每日交易所同步与 SMTP、api/worker 直调 LLM 均未放开出网。
