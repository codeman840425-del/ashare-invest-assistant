# 复审 61b0edf：master_bootstrap 首次导入脚本（运维）

架构师，2026-11-01（America/Denver）。范围：deploy/scripts/master-bootstrap.sh、deploy/runbooks/master-data.md、
scripts/ci/tests/test_master_bootstrap.py。背景：reports/T-A04-ops.md。

## 结论

**可以推送。无 B。** M1 不阻塞推送（T-B52 的 CLI 还没交付，脚本目前只会返回 3），但必须在第一次真实 `--run` 之前修好。

## 核对项

| 要求 | 结果 |
|---|---|
| 只能手动执行 | 通过。up.sh、compose.sh、deploy/compose/*.yml、.github/workflows/*.yml 都不引用（grep 核对；test_no_automatic_trigger 守着）。 |
| 必须带确认开关 | 通过。`--run` 不带 `--confirm-network-fetch` → 退出 4（:73）；只有 `--check` 是默认只读路径。 |
| CI 不触发 | 通过。`CI` / `GITHUB_ACTIONS` 非空时 `--run` 退出 4（:70）；GitHub Actions 两者都设为 true。 |
| 不泄露密钥/证书 | 通过。`set +x` 开头；脚本只打印固定文案和 compose 项目名；psql 在 postgres 容器内用 socket，不拼连接串；一次性容器是 worker（只挂 app_master_key，不挂证书私钥、不持有麦蕊证书，CI 规则 7 守着）。CLI 自身的日志由 T-B52 负责（见 m4）。 |
| 幂等 / 并发 | 通过。已有 status='ok' 的 master_runs 就跳过；flock 防并发；跑完必须看到 ok 行才算成功。 |
| 测试 | 导出目录全量 scripts/ci/tests：583 passed，5 failed 均为 test_secret_scan 的已知环境问题（父提交同样失败）。 |
| shellcheck | 1 warning（m2）+ 1 info（SC2016，有意单引号，可忽略）。CI 未跑 shellcheck。 |

## 问题

- **M1 原始名单文件和库角色还没就位（T-B52 交付前必修）**
  - master-bootstrap.sh:89 在 `run --rm` 的 worker 容器里执行 CLI，但 compose 里没有 `data/master/` 卷（T-A04-ops §1 已指出）。
    CLI 把原始文件写进容器内，容器删掉后文件就没了，而 `master_snapshots.raw_path` 仍指向它，对账和 90 天留存都失效。
  - 修复：给 worker（和 beat 调度的 master.* 任务所在服务）加专用卷 `<前缀>_master`，挂到 raw_path 根目录，属主 10001、700，
    按 T-A04-ops 不进异地备份；runbook 第 2 节写清；加一个 CI 测试：worker 挂了该卷、其他服务不挂。
  - 同时：worker 按新裁定改用 aia_api 后，首次导入写 market.*，需要对这些表的 DML 授权（只 DML，不给 DDL）；
    T-B52 交付时运维在 grants.sql 里补上，verify-roles 验收。
- m1 `--check` 不完全只读、会掩盖错误：cli_present（:51）用 `compose.sh run`，会走完整的 app-master-key-ensure（可能把 .env 里的旧值迁成 secret 文件）；
  而且 `>/dev/null 2>&1` 把 ensure 拒绝、镜像不存在等错误都报成“CLI 未交付”（rc 3）。
  修复：改为 `compose.sh run ... ` 前先 `compose.sh images -q worker` 判断镜像；stderr 不丢弃，ensure 失败按 rc 1 报出；或注释/runbook 改成“不联网、不改库，但会启动一次性容器”。
- m2 shellcheck SC1010：:90 `[ "$(db_state)" = done ]` 的 `done` 加引号（`= "done"`）。
- m3 测试守卫范围不够：test_no_automatic_trigger 只看 up.sh、compose.sh、compose yml、workflows。
  请加上 deploy/docker/*、Dockerfile、scripts/ci/*.sh，以及后端 app/workers/jobs.py 的 TASKS（不得出现 master_bootstrap）。
- m4 日志：T-B52 交付时核对 CLI 只记行数、sha256、来源 URL，不输出整份名单（T-A04-ops §2.3）；本脚本不需要改。
- n1 `XDG_RUNTIME_DIR` 为空时锁文件落在 /tmp（:75）；部署主机通常是单一运维用户，可接受。
