#!/usr/bin/env bash
# 收口：按 deploy/closeout/accepted.manifest 的显式清单合并，再做数据库预演。
# 默认 plan：只打印，不合并、不建库、不调用 docker。
#   deploy/scripts/closeout.sh
#   deploy/scripts/closeout.sh plan
#   deploy/scripts/closeout.sh check
#   deploy/scripts/closeout.sh self-check
#   deploy/scripts/closeout.sh merge [--manifest 文件] [--repo 仓库]
#   deploy/scripts/closeout.sh rehearse-db [--manifest 文件] [--repo 仓库]
#   deploy/scripts/closeout.sh rehearse-neg
#   deploy/scripts/closeout.sh rehearse
#   AIA_CLOSEOUT_DEPLOY=1 deploy/scripts/closeout.sh deploy
#   AIA_CLOSEOUT_CLEAN_NAME=... AIA_CLOSEOUT_CLEAN_DIR=... deploy/scripts/closeout.sh cleanup-iso
# 失败即停。不降级，不 down -v，不 reset/rebase 已有分支，不输出 DSN/口令/密钥。
# 非空旧 signal_events 继续拒迁（T-B92 无已验收交付）。不删行凑空。
{ set +x; } 2>/dev/null
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
MANIFEST="${AIA_CLOSEOUT_MANIFEST:-$ROOT/deploy/closeout/accepted.manifest}"
MODE="${1:-plan}"
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --manifest) MANIFEST="$2"; shift 2 ;;
    --repo) AIA_CLOSEOUT_REPO="$2"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done
export GIT_TERMINAL_PROMPT=0
die() { echo "closeout: $*" >&2; exit 1; }

parse_manifest() {
  [ -f "$MANIFEST" ] || die "找不到清单 $MANIFEST"
  BASE_ROLE=""; BASE_HASH=""; BASE_EVIDENCE=""
  MERGE_N=0
  : > "${AIA_CLOSEOUT_PARSED:-/tmp/closeout-parsed.$$}"
  PARSED="${AIA_CLOSEOUT_PARSED:-/tmp/closeout-parsed.$$}"
  : > "$PARSED"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    IFS='|' read -r kind role hash task evidence <<<"$line"
    case "$kind" in
      BASE)
        [ -n "$BASE_HASH" ] && die "清单里只能有一个 BASE"
        BASE_ROLE=$role; BASE_HASH=$hash; BASE_EVIDENCE=$task
        ;;
      MERGE)
        MERGE_N=$((MERGE_N + 1))
        printf '%s|%s|%s|%s\n' "$role" "$hash" "$task" "$evidence" >> "$PARSED"
        ;;
      *) die "清单行必须以 BASE 或 MERGE 开头" ;;
    esac
    case "$role" in
      [a-z]*) ;;
      *) die "角色名不合法：$role" ;;
    esac
    case "$hash" in
      [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) ;;
      *) die "hash 必须是至少 7 位十六进制，角色 $role" ;;
    esac
  done < "$MANIFEST"
  [ -n "$BASE_HASH" ] || die "清单缺少 BASE"
}

repo_of() {
  if [ -n "${AIA_CLOSEOUT_REPO:-}" ]; then printf '%s\n' "$AIA_CLOSEOUT_REPO"; return; fi
  git -C "$ROOT" rev-parse --show-toplevel
}

resolve_hash() {
  local repo=$1 hash=$2
  git -C "$repo" rev-parse --verify --end-of-options "${hash}^{commit}"
}

require_sources() {
  local miss=0 f
  for f in \
    src/backend/app/db/base.py \
    src/backend/app/db/tables/__init__.py \
    src/backend/alembic.ini \
    src/backend/migrations/env.py \
    src/backend/migrations/versions/0023_t_b85b_mairui_source.py \
    src/backend/migrations/versions/0024_p2n07_plan_times.py \
    src/backend/migrations/versions/0025_p2n06_notification_merge.py \
    src/backend/migrations/versions/0026_p2n06_notification_refs.py \
    config \
    src/frontend/package.json \
    tests/fixtures/mairui
  do
    if [ ! -e "$ROOT/$f" ]; then echo "缺少 $f" >&2; miss=1; fi
  done
  [ "$miss" = 0 ] || die "预演所需源码不在本树。父端补齐后再跑 rehearse-db。不联网补文件。"
}

cmd_plan() {
  parse_manifest
  echo "closeout plan：只读清单，不合并、不建库、不调用 docker。"
  echo "BASE $BASE_ROLE $BASE_HASH"
  echo "MERGE 行数 $MERGE_N"
  echo "模式：plan | check | self-check | merge | rehearse-db | rehearse | deploy"
  echo "rehearse（8 服务）未执行：网络预检被中断且禁止重试，本脚本不探测 docker 网络。"
  echo "rehearse-db：已有 PG16 镜像，docker run --network none，专属 unix socket，私有随机凭据。不查询守护进程，不创建网络。"
  echo "顺序：0023、合成旧通知、备份、非空旧事件门、alembic head、与 heads 对照、timescale、apply-roles 与 verify-roles 各两遍、保留校验。"
  echo "signal_events 非 0 则停。不升级、不删行。T-B92 没有已验收交付。"
  echo "rehearse-neg：另一库插入两条合法旧事件，期望升级失败且版本与计数不变。退出 2 表示阻塞仍在，不是升级成功。"
  echo "deploy 需要 AIA_CLOSEOUT_DEPLOY=1。self-check 即使继承该开关也只模拟。up.sh 已含迁移、timescale-apply、db-roles 和 --wait；之后才是 db-roles 容器内 verify-roles、nginx -t、HTTP 与 8 服务状态。失败即停。不重复迁移。"
}

cmd_merge() {
  parse_manifest
  local repo wt ts branch
  repo="$(repo_of)"
  resolve_hash "$repo" "$BASE_HASH" >/dev/null || die "BASE $BASE_HASH 不在本地对象库。不 fetch。"
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  branch="closeout/rehearse-$ts"
  wt="$(mktemp -d "${TMPDIR:-/tmp}/closeout-wt.XXXXXX")"
  git -C "$repo" worktree add -b "$branch" "$wt" "$(resolve_hash "$repo" "$BASE_HASH")"
  local role hash task evidence full files
  while IFS='|' read -r role hash task evidence; do
    [ -n "$role" ] || continue
    if ! full="$(resolve_hash "$repo" "$hash" 2>/dev/null)"; then
      echo "closeout: 冲突前停止。角色=$role 任务=$task hash=$hash 不在本地，不 fetch。" >&2
      exit 1
    fi
    if ! git -C "$wt" merge --no-ff --no-edit -m "closeout: $task $full" "$full"; then
      files="$(git -C "$wt" diff --name-only --diff-filter=U 2>/dev/null || true)"
      git -C "$wt" merge --abort
      echo "closeout: 合并冲突，已停止。不替该角色修改。" >&2
      echo "责任角色=$role 任务=$task hash=$full" >&2
      echo "冲突文件：" >&2
      printf '%s\n' "$files" >&2
      echo "临时分支 $branch 停在冲突前。未 reset 其他分支。" >&2
      exit 1
    fi
    echo "merged $task $role ${full:0:12}"
  done < "$PARSED"
  echo "closeout branch: $branch"
  echo "worktree: $wt"
}

cmd_rehearse() {
  echo "closeout: 8 服务隔离演练阻塞。" >&2
  echo "只读 docker 网络预检曾被用户中断，禁止重试或改宿主网络。" >&2
  echo "因此不启动 api/worker/ingest/beat/signal-rt/nginx/postgres/redis，也不宣称 healthy。" >&2
  echo "数据库半段用 rehearse-db（专属 unix socket，不创建 docker 网络）。" >&2
  exit 2
}

scrub_log() {
  local log=$1 dir="${AIA_DB_ROLE_PASSWORD_DIR:-}"
  [ -n "$dir" ] && [ -d "$dir" ] && [ -f "$log" ] || return 0
  python3 - "$log" "$dir" <<'PY'
import pathlib, sys
log, pwdir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
text = log.read_bytes()
for p in pwdir.iterdir():
    if not p.is_file():
        continue
    secret = p.read_bytes().strip()
    if secret:
        text = text.replace(secret, b"[redacted]")
log.write_bytes(text)
PY
}

step() {
  local name=$1
  shift
  if [ -n "${AIA_CLOSEOUT_STEPLOG:-}" ]; then printf '%s\n' "$name" >> "$AIA_CLOSEOUT_STEPLOG"; fi
  if [ "${AIA_CLOSEOUT_FAIL_AT:-}" = "$name" ]; then
    echo "closeout: 停在 $name" >&2
    exit 1
  fi
  if [ "${AIA_CLOSEOUT_SIMULATE:-}" = 1 ]; then
    return 0
  fi
  if [ -n "${AIA_CLOSEOUT_LOGDIR:-}" ]; then
    local log="$AIA_CLOSEOUT_LOGDIR/$name.log"
    if ! "$@" >"$log" 2>&1; then
      scrub_log "$log"
      echo "closeout: 步骤 $name 失败，日志 $log" >&2
      exit 1
    fi
    scrub_log "$log"
    return 0
  fi
  "$@"
}

pg_image() {
  awk '/image: timescale\/timescaledb/ { print $2; exit }' "$ROOT/deploy/compose/docker-compose.yml"
}

iso_pg_up() {
  local data=$1 name=$2 image mode i ok=0
  image="$(pg_image)"
  [ -n "$image" ] || die "compose 里没有 timescale 镜像"
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    die "本地没有该 PG 镜像。不拉取。"
  fi
  mkdir -p -m 700 "$data/pw" "$data/log" "$data/sock"
  chmod 1777 "$data/sock"
  umask 077
  python3 -c 'import secrets; print(secrets.token_hex(24))' > "$data/pw/owner"
  local r
  for r in aia_api aia_ingest aia_maint; do
    python3 -c 'import secrets; print(secrets.token_hex(24))' > "$data/pw/$r"
    cp "$data/pw/$r" "$data/pw/db_password_$r"
  done
  chmod 644 "$data/pw/owner"
  chmod 711 "$data/pw"
  if ! docker run -d --name "$name" --network none \
    -v "$data/sock:/var/run/postgresql" \
    -v "$data/pw/owner:/run/pwo:ro" \
    -e POSTGRES_USER=aia -e POSTGRES_DB=aia \
    -e POSTGRES_PASSWORD_FILE=/run/pwo \
    -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
    -e POSTGRES_INITDB_ARGS=--auth-local=scram-sha-256 \
    "$image" >/dev/null; then
    chmod 600 "$data/pw/owner" || true
    chmod 700 "$data/pw" || true
    die "容器没有启动。目录保留，不删除。"
  fi
  mode="$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$name")"
  if [ "$mode" != none ]; then
    chmod 600 "$data/pw/owner" || true
    chmod 700 "$data/pw" || true
    die "容器网络模式是 ${mode}。不改宿主网络，不删除容器。"
  fi
  for i in $(seq 60); do
    if PGHOST="$data/sock" PGUSER=aia PGDATABASE=aia PGPASSWORD="$(cat "$data/pw/owner")" \
      psql -XtAc 'select 1' >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 1
  done
  chmod 600 "$data/pw/owner"
  chmod 700 "$data/pw"
  [ "$ok" = 1 ] || die "数据库在 60 秒内没有就绪。容器保留，不删除。"
  if PGHOST="$data/sock" PGUSER=aia PGDATABASE=aia PGPASSWORD=wrong \
    psql -XtAc 'select 1' >/dev/null 2>&1; then
    die "认证未生效"
  fi
  echo "iso-pg up: $name（network none，日志在 $data/log）"
}

require_db_tools() {
  require_sources
  command -v psql >/dev/null 2>&1 || die "没有 psql"
  command -v pg_dump >/dev/null 2>&1 || die "没有 pg_dump"
  command -v uv >/dev/null 2>&1 || die "没有 uv。不用宿主 initdb 代替。"
  command -v docker >/dev/null 2>&1 || die "没有 docker 客户端。不改用宿主 initdb。"
  command -v python3 >/dev/null 2>&1 || die "没有 python3"
}

start_iso() {
  local ts data name
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  data="$(mktemp -d "${TMPDIR:-/tmp}/closeout-pg.XXXXXX")"
  name="aia-closeout-pg-$ts"
  echo "closeout：目录 $data 容器 $name。失败不删除、不降级。"
  iso_pg_up "$data" "$name"
  export PGHOST="$data/sock" PGUSER=aia PGDATABASE=aia
  export AIA_DB_ROLE_PASSWORD_DIR="$data/pw" AIA_PSQL_MODE=direct AIA_ROOT="$ROOT"
  export AIA_CLOSEOUT_LOGDIR="$data/log"
  export PGPASSWORD
  PGPASSWORD="$(cat "$data/pw/owner")"
}

run_alembic() {
  local db=$1 target=$2
  ( cd "$ROOT/src/backend" && DATABASE_URL="postgresql+psycopg://aia@/${db}?host=${PGHOST}" uv run alembic upgrade "$target" )
}

dump_before() {
  umask 077
  pg_dump -Fc -f "${PGHOST%/sock}/before-head.dump"
}

gate_nonempty_events() {
  local n
  n="$(psql -XtAc 'SELECT count(*) FROM app.signal_events' | tr -d '[:space:]')"
  case "$n" in
    0) ;;
    ''|*[!0-9]*) die "无法确认 signal_events 计数，停止升级" ;;
    *)
      echo "closeout: 阻塞 T-B92。signal_events=$n 非空。没有已验收的旧事件归属修复。不升级、不删行、不降级。" >&2
      exit 1
      ;;
  esac
}

assert_head() {
  local heads n head now
  heads="$(cd "$ROOT/src/backend" && DATABASE_URL="postgresql+psycopg://aia@/aia?host=${PGHOST}" uv run alembic heads)"
  n="$(printf '%s\n' "$heads" | grep -c '[0-9a-f]' || true)"
  [ "$n" = 1 ] || die "alembic heads 不是单一头，停止。不挑选其中一个。"
  head="$(printf '%s\n' "$heads" | awk 'NR==1 { print $1 }')"
  now="$(psql -tAc "SELECT version_num FROM public.alembic_version" | tr -d '[:space:]')"
  [ -n "$head" ] && [ "$now" = "$head" ] || die "迁移后版本 ${now:-空} 与 heads ${head:-空} 不一致。不降级。"
  echo "closeout: 版本与 alembic heads 一致（$head）"
}

cmd_rehearse_db() {
  if [ "${AIA_CLOSEOUT_SIMULATE:-}" != 1 ]; then
    require_db_tools
    start_iso
  fi
  step alembic-0023 run_alembic aia 0023
  step synthetic psql -X -v ON_ERROR_STOP=1 -f "$ROOT/deploy/db/closeout/synthetic-0023.sql"
  step assert-0023 psql -X -v ON_ERROR_STOP=1 -f "$ROOT/deploy/db/closeout/assert-0023.sql"
  step backup dump_before
  step gate-old-events gate_nonempty_events
  step alembic-head run_alembic aia head
  step assert-head assert_head
  step timescale "$ROOT/deploy/scripts/db-apply-timescale.sh" --db aia
  step apply-roles "$ROOT/deploy/db/roles/apply-roles.sh"
  step apply-roles-2 "$ROOT/deploy/db/roles/apply-roles.sh"
  step verify-roles "$ROOT/deploy/db/roles/verify-roles.sh"
  step verify-roles-2 "$ROOT/deploy/db/roles/verify-roles.sh"
  step assert-retained psql -X -v ON_ERROR_STOP=1 -f "$ROOT/deploy/db/closeout/assert-retained.sql"
  if [ "${AIA_CLOSEOUT_SIMULATE:-}" != 1 ]; then
    echo "closeout rehearse-db 完成。signal_events 为 0 才升级。未启动 8 服务。容器与日志保留。"
  fi
}

neg_createdb() { psql -d aia -v ON_ERROR_STOP=1 -c 'CREATE DATABASE aia_neg'; }
neg_synth() { psql -d aia_neg -X -v ON_ERROR_STOP=1 -f "$ROOT/deploy/db/closeout/synthetic-0023.sql"; }
neg_insert() {
  psql -d aia_neg -v ON_ERROR_STOP=1 -c "INSERT INTO app.signal_events (scope, user_id, security_code, trigger_kind, from_state, to_state) VALUES ('user', '00000000-0000-4000-8000-000000000001', '600000.SH', 'flip', 'a', 'b')"
  psql -d aia_neg -v ON_ERROR_STOP=1 -c "INSERT INTO app.signal_events (scope, security_code, trigger_kind) VALUES ('shared', '600000.SH', 'stale')"
}
neg_upgrade() {
  local log rc
  log="${AIA_CLOSEOUT_LOGDIR}/neg-upgrade-detail.log"
  set +e
  run_alembic aia_neg head >"$log" 2>&1
  rc=$?
  set -e
  scrub_log "$log"
  if [ "$rc" = 0 ]; then
    die "非空旧事件升级返回成功。T-B92 没有已验收交付，不能当成迁移成功。不降级、不删行。"
  fi
  if ! grep -q 'unowned_signal_events_require_ruling' "$log"; then
    die "升级失败但日志里没有拒迁错误。不降级、不删行。日志 $log"
  fi
}
neg_assert_stay() {
  local ver n
  ver="$(psql -d aia_neg -tAc "SELECT version_num FROM public.alembic_version" | tr -d '[:space:]')"
  n="$(psql -d aia_neg -tAc "SELECT count(*) FROM app.signal_events" | tr -d '[:space:]')"
  [ "$ver" = "0023" ] || die "拒迁后版本是 ${ver:-空}，不是 0023。不删行、不降级。"
  [ "$n" = "2" ] || die "拒迁后 signal_events 计数是 ${n:-空}，不是 2。不删行。"
}

cmd_rehearse_neg() {
  if [ "${AIA_CLOSEOUT_SIMULATE:-}" != 1 ]; then
    require_db_tools
    start_iso
  fi
  step neg-db neg_createdb
  step neg-0023 run_alembic aia_neg 0023
  step neg-synth neg_synth
  step neg-insert neg_insert
  step neg-upgrade neg_upgrade
  step neg-assert-stay neg_assert_stay
  if [ "${AIA_CLOSEOUT_SIMULATE:-}" = 1 ]; then
    echo "closeout: 模拟未连库。真实阻塞：T-B92 无已验收交付，非空旧事件应拒迁。退出 2 不是升级成功。" >&2
    exit 2
  fi
  echo "closeout: 阻塞仍在 T-B92。非空旧事件未升级，版本与计数未改。这不是迁移成功。" >&2
  exit 2
}

cmd_cleanup_iso() {
  local name="${AIA_CLOSEOUT_CLEAN_NAME:-}" dir="${AIA_CLOSEOUT_CLEAN_DIR:-}" image
  case "$name" in
    aia-closeout-pg-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) ;;
    *) die "只清理本任务的 aia-closeout-pg- 容器" ;;
  esac
  case "$dir" in
    /tmp/*|"${TMPDIR:-/tmp}"/*) ;;
    *) die "工作目录必须在临时目录下" ;;
  esac
  [ -d "$dir/sock" ] || die "没有本任务 socket 目录，不清理其他路径"
  image="$(pg_image)"
  [ -n "$image" ] || die "compose 里没有 timescale 镜像"
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run --rm --network none -v "$dir/sock:/s" "$image" sh -c 'rm -f /s/.s.PGSQL.*'
  rmdir "$dir/sock" 2>/dev/null || true
  echo "已移除容器 $name 与 socket。日志和口令目录仍在 $dir。"
}

check_http() {
  local port="${NGINX_HTTP_PORT:-8080}" path code
  for path in / /login /api/v1/health/live; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}${path}")"
    [ "$code" = 200 ] || die "HTTP $path 状态 $code"
    echo "HTTP $path 200"
  done
}

check_services() {
  local s id st
  for s in api worker ingest beat signal-rt nginx postgres redis; do
    id="$("$HERE/compose.sh" ps -q "$s" | head -n1)"
    [ -n "$id" ] || die "没有服务 $s"
    st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id")"
    [ "$st" = healthy ] || die "$s 状态 $st"
    echo "$s healthy"
  done
}

run_backup() {
  if [ "${AIA_CLOSEOUT_SELF_CHECK:-}" = 1 ]; then
    if [ -n "${AIA_CLOSEOUT_REAL_MARK:-}" ]; then printf '%s\n' backup >> "$AIA_CLOSEOUT_REAL_MARK"; fi
    die "self-check 禁止真实备份"
  fi
  "$HERE/db-backup.sh"
}
run_up() {
  if [ "${AIA_CLOSEOUT_SELF_CHECK:-}" = 1 ]; then
    if [ -n "${AIA_CLOSEOUT_REAL_MARK:-}" ]; then printf '%s\n' up >> "$AIA_CLOSEOUT_REAL_MARK"; fi
    die "self-check 禁止真实启动"
  fi
  "$HERE/up.sh"
}
verify_in_db_roles() {
  if [ "${AIA_CLOSEOUT_SELF_CHECK:-}" = 1 ]; then
    if [ -n "${AIA_CLOSEOUT_REAL_MARK:-}" ]; then printf '%s\n' verify >> "$AIA_CLOSEOUT_REAL_MARK"; fi
    die "self-check 禁止真实校验"
  fi
  "$HERE/compose.sh" run --no-deps --rm --entrypoint bash db-roles /aia/deploy/db/roles/verify-roles.sh
}
cmd_deploy() {
  if [ "${AIA_CLOSEOUT_SELF_CHECK:-}" = 1 ] && [ "${AIA_CLOSEOUT_SIMULATE:-}" != 1 ]; then
    die "self-check 禁止真实部署"
  fi
  [ "${AIA_CLOSEOUT_DEPLOY:-}" = 1 ] || die "真实部署被拒绝。设置 AIA_CLOSEOUT_DEPLOY=1 才会调用 up.sh。默认不做。"
  echo "closeout deploy：up.sh 已包含迁移、timescale-apply 和 db-roles。校验在 db-roles 容器内执行。失败即停，不重复迁移。" >&2
  step backup run_backup
  step up run_up
  step verify-roles verify_in_db_roles
  step nginx-t "$HERE/compose.sh" exec -T nginx nginx -t
  step http check_http
  step services check_services
}

cmd_self_check() {
  export AIA_CLOSEOUT_SELF_CHECK=1
  bash -n "$0"
  if grep -E 'alembic[[:space:]]+downgrade|compose[[:space:]].*[[:space:]]down[[:space:]]' "$0" >/dev/null; then
    die "脚本含降级或 down"
  fi
  if grep -E 'docker[[:space:]]+(info|network)' "$0" >/dev/null; then
    die "脚本含被禁止的 docker 网络预检"
  fi
  local tmp repo base a b
  tmp="$(mktemp -d)"
  repo="$tmp/repo"
  git init -q -b main "$repo"
  git -C "$repo" config user.email t@example.com
  git -C "$repo" config user.name t
  echo base > "$repo/f"
  git -C "$repo" add f
  git -C "$repo" commit -q -m base
  base="$(git -C "$repo" rev-parse HEAD)"
  git -C "$repo" checkout -q -b ops
  echo ops > "$repo/f"
  git -C "$repo" commit -q -am ops
  a="$(git -C "$repo" rev-parse HEAD)"
  git -C "$repo" checkout -q "$base"
  git -C "$repo" checkout -q -b testrole
  echo test > "$repo/f"
  git -C "$repo" commit -q -am test
  b="$(git -C "$repo" rev-parse HEAD)"
  git -C "$repo" checkout -q main
  printf '%s\n' \
    "BASE|shared-main|$base|fixture" \
    "MERGE|ops|$a|T-OPS|ok" \
    "MERGE|test|$b|T-TEST|conflicts" > "$tmp/m"
  set +e
  out="$(AIA_CLOSEOUT_REPO="$repo" AIA_CLOSEOUT_MANIFEST="$tmp/m" "$0" merge 2>&1)"
  rc=$?
  set -e
  [ "$rc" != 0 ] || die "冲突合并应当失败"
  printf '%s\n' "$out" | grep -q '责任角色=test' || die "未记录责任角色"
  [ "$(git -C "$repo" rev-parse ops)" = "$a" ] || die "ops 分支被改动"
  [ "$(git -C "$repo" rev-parse testrole)" = "$b" ] || die "test 分支被改动"
  echo "closeout self-check：冲突停手且未 reset 来源分支"
  local bad='PGPASSWORD'
  bad="${bad}}@"
  if grep -F "$bad" "$0" >/dev/null; then
    die "口令写进了数据库地址"
  fi
  local log bin
  log="$tmp/steps"
  : > "$log"
  set +e
  out="$(AIA_CLOSEOUT_STEPLOG="$log" "$0" deploy 2>&1)"
  rc=$?
  set -e
  [ "$rc" != 0 ] || die "未授权的 deploy 应当失败"
  [ ! -s "$log" ] || die "未授权的 deploy 不应记录步骤"
  mark="$tmp/real-exec"
  : > "$mark"
  : > "$log"
  set +e
  out="$(AIA_CLOSEOUT_DEPLOY=1 AIA_CLOSEOUT_SELF_CHECK=1 AIA_CLOSEOUT_REAL_MARK="$mark" AIA_CLOSEOUT_STEPLOG="$log" "$0" deploy 2>&1)"
  rc=$?
  set -e
  [ "$rc" != 0 ] || die "继承部署开关时 self-check 仍应拒绝"
  [ ! -s "$log" ] || die "继承部署开关时不应记录步骤"
  [ ! -s "$mark" ] || die "继承部署开关时调用了真实执行器"
  printf '%s\n' "$out" | grep -q '禁止真实部署' || die "未拒绝真实部署"
  : > "$log"
  set +e
  AIA_CLOSEOUT_DEPLOY=1 AIA_CLOSEOUT_SIMULATE=1 AIA_CLOSEOUT_STEPLOG="$log" AIA_CLOSEOUT_FAIL_AT=verify-roles "$0" deploy >/dev/null 2>&1
  rc=$?
  set -e
  [ "$rc" != 0 ] || die "deploy 应在 verify-roles 停下"
  [ "$(cat "$log")" = $'backup\nup\nverify-roles' ] || die "deploy 失败短路顺序不对：$(cat "$log")"
  : > "$log"
  set +e
  AIA_CLOSEOUT_SIMULATE=1 AIA_CLOSEOUT_STEPLOG="$log" AIA_CLOSEOUT_FAIL_AT=timescale "$0" rehearse-db >/dev/null 2>&1
  rc=$?
  set -e
  [ "$rc" != 0 ] || die "rehearse-db 应在 timescale 停下"
  [ "$(cat "$log")" = $'alembic-0023\nsynthetic\nassert-0023\nbackup\ngate-old-events\nalembic-head\nassert-head\ntimescale' ] \
    || die "timescale 之前的顺序不对：$(cat "$log")"
  : > "$log"
  set +e
  AIA_CLOSEOUT_SIMULATE=1 AIA_CLOSEOUT_STEPLOG="$log" AIA_CLOSEOUT_FAIL_AT=gate-old-events "$0" rehearse-db >/dev/null 2>&1
  rc=$?
  set -e
  [ "$rc" != 0 ] || die "非空门应当能停下"
  printf '%s\n' "$(cat "$log")" | grep -qx alembic-head && die "非空门之后不应升级"
  : > "$log"
  AIA_CLOSEOUT_SIMULATE=1 AIA_CLOSEOUT_STEPLOG="$log" "$0" rehearse-db
  [ "$(cat "$log")" = $'alembic-0023\nsynthetic\nassert-0023\nbackup\ngate-old-events\nalembic-head\nassert-head\ntimescale\napply-roles\napply-roles-2\nverify-roles\nverify-roles-2\nassert-retained' ] \
    || die "rehearse-db 全序不对：$(cat "$log")"
  set +e
  out="$("$0" rehearse 2>&1)"
  rc=$?
  set -e
  [ "$rc" = 2 ] || die "rehearse 应退出 2"
  printf '%s\n' "$out" | grep -q 'docker run' && die "rehearse 不应启动容器"
  : > "$log"
  set +e
  out="$(AIA_CLOSEOUT_SIMULATE=1 AIA_CLOSEOUT_STEPLOG="$log" "$0" rehearse-neg 2>&1)"
  rc=$?
  set -e
  [ "$rc" = 2 ] || die "rehearse-neg 模拟应退出 2"
  printf '%s\n' "$out" | grep -q 'T-B92' || die "rehearse-neg 未报告 T-B92"
  [ "$(cat "$log")" = $'neg-db\nneg-0023\nneg-synth\nneg-insert\nneg-upgrade\nneg-assert-stay' ] \
    || die "rehearse-neg 顺序不对：$(cat "$log")"
  set +e
  out="$(AIA_CLOSEOUT_CLEAN_NAME=postgres AIA_CLOSEOUT_CLEAN_DIR=/tmp/x "$0" cleanup-iso 2>&1)"
  rc=$?
  set -e
  [ "$rc" != 0 ] || die "清理应拒绝其他容器名"
  printf '%s\n' "$out" | grep -q '只清理' || die "清理拒绝信息缺失"
  set +e
  out="$(AIA_CLOSEOUT_CLEAN_NAME=aia-closeout-pg-20261108T091500Z AIA_CLOSEOUT_CLEAN_DIR=/etc "$0" cleanup-iso 2>&1)"
  rc=$?
  set -e
  [ "$rc" != 0 ] || die "清理应拒绝临时目录之外的路径"
  bin="$tmp/bin"
  mkdir -p "$bin"
  cat > "$bin/psql" << 'EOF'
#!/bin/bash
printf '%s\n' "${MOCK_SIGNAL_EVENTS:?}"
EOF
  chmod +x "$bin/psql"
  sed -n '/^gate_nonempty_events()/,/^}/p' "$0" > "$tmp/gate.sh"
  {
    echo 'die() { echo "closeout: $*" >&2; exit 1; }'
    cat "$tmp/gate.sh"
    echo 'gate_nonempty_events'
  } > "$tmp/run-gate.sh"
  set +e
  out="$(PATH="$bin:$PATH" MOCK_SIGNAL_EVENTS=2 bash "$tmp/run-gate.sh" 2>&1)"
  rc=$?
  set -e
  [ "$rc" != 0 ] || die "非空计数应当失败"
  printf '%s\n' "$out" | grep -q 'T-B92' || die "非空计数未指向 T-B92"
  PATH="$bin:$PATH" MOCK_SIGNAL_EVENTS=0 bash "$tmp/run-gate.sh"
  echo "closeout self-check：顺序、失败短路、非空门、清理拒绝"
}

case "$MODE" in
  plan) cmd_plan ;;
  check) parse_manifest; echo "清单可解析 BASE=$BASE_HASH MERGE=$MERGE_N"; require_sources ;;
  merge) cmd_merge ;;
  rehearse-db) cmd_rehearse_db ;;
  rehearse-neg) cmd_rehearse_neg ;;
  rehearse) cmd_rehearse ;;
  deploy) cmd_deploy ;;
  cleanup-iso) cmd_cleanup_iso ;;
  self-check) cmd_self_check ;;
  *) die "未知模式 $MODE" ;;
esac
