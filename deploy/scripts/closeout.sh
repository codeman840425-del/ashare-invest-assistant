#!/usr/bin/env bash
# 收口：按 deploy/closeout/accepted.manifest 的显式清单合并，再做数据库预演。
# 默认 plan：只打印，不合并、不建库、不调用 docker。
#   deploy/scripts/closeout.sh
#   deploy/scripts/closeout.sh plan
#   deploy/scripts/closeout.sh check
#   deploy/scripts/closeout.sh self-check
#   deploy/scripts/closeout.sh merge [--manifest 文件] [--repo 仓库]
#   deploy/scripts/closeout.sh rehearse-db [--manifest 文件] [--repo 仓库]
#   deploy/scripts/closeout.sh rehearse
#   AIA_CLOSEOUT_DEPLOY=1 deploy/scripts/closeout.sh deploy
# 失败即停。不降级，不 down -v，不 reset/rebase 已有分支，不输出 DSN/口令/密钥。
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
  echo "rehearse-db：本机 PG16、--network none 不可用时用专属 unix socket；迁到 0023、灌合成旧通知、再升到 alembic heads。"
  echo "deploy 需要 AIA_CLOSEOUT_DEPLOY=1，且不会 down -v、不会降级、不会重生成已有凭据。"
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

cmd_rehearse_db() {
  require_sources
  command -v initdb >/dev/null 2>&1 || die "没有 initdb"
  command -v psql >/dev/null 2>&1 || die "没有 psql"
  command -v alembic >/dev/null 2>&1 || die "没有 alembic。不改用手工 SQL 冒充迁移。"
  local data sock ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  data="$(mktemp -d "${TMPDIR:-/tmp}/closeout-pg.XXXXXX")"
  sock="$data/sock"
  mkdir -p "$sock"
  echo "closeout rehearse-db：数据目录 $data （失败不删除、不降级）"
  initdb -D "$data/pg" --username=aia --auth=trust --encoding=UTF8 --locale=C >/dev/null
  pg_ctl -D "$data/pg" -o "-k $sock -c listen_addresses='' -c unix_socket_directories=$sock" -l "$data/server.log" start >/dev/null
  export PGHOST="$sock" PGUSER=aia PGDATABASE=aia
  createdb -h "$sock" -U aia aia
  (
    cd "$ROOT/src/backend"
    env DATABASE_URL="postgresql+psycopg://aia@/aia?host=${sock}" alembic upgrade 0023
  )
  psql -h "$sock" -U aia -d aia -v ON_ERROR_STOP=1 -f "$ROOT/deploy/db/closeout/synthetic-0023.sql" >/dev/null
  psql -h "$sock" -U aia -d aia -v ON_ERROR_STOP=1 -f "$ROOT/deploy/db/closeout/assert-0023.sql" >/dev/null
  umask 077
  pg_dump -h "$sock" -U aia -d aia -Fc -f "$data/before-0024.dump"
  local head
  head="$(cd "$ROOT/src/backend" && env DATABASE_URL="postgresql+psycopg://aia@/aia?host=${sock}" alembic heads | awk 'NR==1{print $1}')"
  [ -n "$head" ] || die "alembic heads 为空"
  (
    cd "$ROOT/src/backend"
    env DATABASE_URL="postgresql+psycopg://aia@/aia?host=${sock}" alembic upgrade head
  )
  local now
  now="$(psql -h "$sock" -U aia -d aia -tAc "SELECT version_num FROM public.alembic_version")"
  [ "$now" = "$head" ] || die "迁移后版本 $now 不是 heads $head"
  psql -h "$sock" -U aia -d aia -v ON_ERROR_STOP=1 -f "$ROOT/deploy/db/closeout/assert-retained.sql" >/dev/null
  echo "closeout rehearse-db：旧事件计数保留，head=$head。未跑 8 服务，未跑 verify-roles（需口令目录，由调用方在同一 socket 上继续）。"
  echo "数据目录仍在 $data"
}

cmd_deploy() {
  [ "${AIA_CLOSEOUT_DEPLOY:-}" = 1 ] || die "真实部署被拒绝。设置 AIA_CLOSEOUT_DEPLOY=1 才会调用 up.sh。默认不做。"
  echo "closeout deploy：先备份，再 up.sh。不会删除数据卷，不会执行降级，不会覆盖已有密钥。" >&2
  "$HERE/db-backup.sh"
  "$HERE/up.sh"
}

cmd_self_check() {
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
}

case "$MODE" in
  plan) cmd_plan ;;
  check) parse_manifest; echo "清单可解析 BASE=$BASE_HASH MERGE=$MERGE_N"; require_sources ;;
  merge) cmd_merge ;;
  rehearse-db) cmd_rehearse_db ;;
  rehearse) cmd_rehearse ;;
  deploy) cmd_deploy ;;
  self-check) cmd_self_check ;;
  *) die "未知模式 $MODE" ;;
esac
