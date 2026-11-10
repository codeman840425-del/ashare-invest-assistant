#!/usr/bin/env bash
# 证券主数据首次导入（T-A04 / plan §4.6.6；CLI app.cli.master_bootstrap 由后端 T-B52 交付）。
# 首次导入要联网拉交易所公开名单，所以是**显式的手动步骤**：up.sh、compose 服务、CI 都不调用本脚本（CI 测试守着）。
#   master-bootstrap.sh --check                                # 只读：判断是否需要执行（不联网、不改库）
#   master-bootstrap.sh --run --confirm-network-fetch          # 需要时执行一次；已完成则跳过（幂等）
#   master-bootstrap.sh --rebuild-search-terms                 # 默认 dry-run：只说明将把该开关传给 CLI，不联网、不写库
#   master-bootstrap.sh --run --confirm-network-fetch --rebuild-search-terms
#        在首次导入合并来源后显式重建检索词条（后端 app.cli master-bootstrap --rebuild-search-terms，默认关闭）
# --check 退出码：0 = 不需要（已有 status='ok' 的 master_runs）；10 = 需要；3 = 未就绪（表不存在 / CLI 未交付）；其余 = 出错。
# --run：先做 --check；不需要就直接成功退出；需要才用 opt-in profile 跑 master-bootstrap 服务
#        （compose.sh --profile master-bootstrap run --rm --no-deps -T，不启动 ingest、不走 worker），
#        跑完再查一次，必须出现 status='ok' 的记录才算成功。同一主机同一项目用 flock 防并发。
# 不调用麦蕊：容器只拉交易所公开列表；worker 不持有麦蕊证书（只有 ingest 能解密，CI 规则守着）；按证书对账（麦蕊）只由 beat 日常任务经 ingest 做，
#   不属于首次导入（T-B52 须保证 bootstrap 不链式触发 master.reconcile_vendor）。
# CI（CI / GITHUB_ACTIONS 非空）下拒绝 --run。不打印连接串、口令。
{ set +x; } 2>/dev/null
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE="${AIA_MASTER_BOOTSTRAP_COMPOSE:-$ROOT/deploy/scripts/compose.sh}"  # 测试可替换
CLI_MODULE="app.cli.master_bootstrap"
die() { echo "master-bootstrap: $1" >&2; exit "${2:-2}"; }
log() { echo "master-bootstrap: $*" >&2; }

mode=""; confirm=0; rebuild_terms=0
while [ $# -gt 0 ]; do
  case "$1" in
    --check) [ -z "$mode" ] || die "--check 与 --run 只能选一个"; mode=check; shift ;;
    --run) [ -z "$mode" ] || die "--check 与 --run 只能选一个"; mode=run; shift ;;
    --confirm-network-fetch) confirm=1; shift ;;
    --rebuild-search-terms) rebuild_terms=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) die "未知参数：$1" ;;
  esac
done
if [ -z "$mode" ]; then
  if [ "$rebuild_terms" = 1 ]; then
    log "dry-run：--rebuild-search-terms 已识别，不会联网、不会写库"
    log "真正写入须：master-bootstrap.sh --run --confirm-network-fetch --rebuild-search-terms"
    log "后端入口：python -m app.cli master-bootstrap --rebuild-search-terms（默认关闭；只在显式开关下重建词条，不另启外呼）"
    exit 0
  fi
  die "用法：master-bootstrap.sh --check | --run --confirm-network-fetch [--rebuild-search-terms] | --rebuild-search-terms"
fi

# 统一入口（测试可替换 COMPOSE）
cmp() { "$COMPOSE" "$@"; }

sql() {  # stdin = SQL；只读事务；输出一行
  cmp exec -T postgres sh -c 'exec psql -X -q -At -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}"'
}

db_state() {  # 打印 no_table / done / needed
  local t
  t="$(printf '%s\n' "BEGIN READ ONLY;" "SELECT coalesce(to_regclass('market.master_runs')::text, '');" "ROLLBACK;" | sql)" \
    || die "查询数据库失败（postgres 是否在运行？先 deploy/scripts/up.sh）" 1
  if [ -z "$t" ]; then echo no_table; return; fi
  t="$(printf '%s\n' "BEGIN READ ONLY;" \
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM market.master_runs WHERE status = 'ok') THEN 'done' ELSE 'needed' END;" \
        "ROLLBACK;" | sql)" || die "查询 market.master_runs 失败" 1
  case "$t" in done|needed) echo "$t" ;; *) die "market.master_runs 查询结果异常" 1 ;; esac
}

cli_present() {  # 镜像里有没有 CLI 模块（只 import 检查，不执行）
  cmp run --rm --no-deps -T --entrypoint python worker -c \
    "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$CLI_MODULE') else 1)" >/dev/null 2>&1
}

check() {  # 返回码同 --check
  local s; s="$(db_state)"
  case "$s" in
    no_table) log "未就绪：market.master_runs 不存在（迁移还没到 T-B52 的版本）"; return 3 ;;
    done) log "不需要：已有 status='ok' 的主数据同步记录"; return 0 ;;
  esac
  if ! cli_present; then log "未就绪：镜像里没有 $CLI_MODULE（T-B52 未交付或镜像未重建）"; return 3; fi
  log "需要执行：还没有成功的主数据同步记录"; return 10
}

if [ "$mode" = check ]; then
  rc=0; check || rc=$?; exit "$rc"
fi

# --run
if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
  die "CI 环境下拒绝执行首次导入（要联网拉交易所名单，只能由运维手动执行）" 4
fi
[ "$confirm" = 1 ] || die "首次导入要联网拉交易所公开名单：确认后加 --confirm-network-fetch 再运行" 4

lock_dir="${XDG_RUNTIME_DIR:-/tmp}"
project="$(cmp --get COMPOSE_PROJECT_NAME 2>/dev/null || echo default)"
[[ "$project" =~ ^[A-Za-z0-9_-]+$ ]] || project=default
exec 9>"$lock_dir/aia-master-bootstrap-$project.lock"
flock -n 9 || die "另一个 master-bootstrap 正在运行（项目 $project）" 5

rc=0; check || rc=$?
case "$rc" in
  0) log "跳过（幂等）"; exit 0 ;;
  10) ;;
  *) exit "$rc" ;;
esac

cli_args=()
if [ "$rebuild_terms" = 1 ]; then
  cli_args+=(--rebuild-search-terms)
  log "将向 CLI 传递 --rebuild-search-terms（合并来源后显式重建检索词条）"
fi
log "开始首次导入（profile master-bootstrap，--rm --no-deps，不走 worker）"
cmp --profile master-bootstrap run --rm --no-deps -T master-bootstrap "${cli_args[@]}" \
  || die "$CLI_MODULE 失败；查看上面的输出后重试（幂等）" 1
[ "$(db_state)" = done ] || die "CLI 退出 0 但没有 status='ok' 的 master_runs 记录，视为失败" 1
log "完成：已有 status='ok' 的主数据同步记录，可以开放服务"
