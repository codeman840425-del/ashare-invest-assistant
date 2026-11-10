#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2012
# shellcheck source=lib.sh
{ set +x; } 2>/dev/null
set -euo pipefail
WRAPUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck disable=SC1091
# shellcheck disable=SC2012
. "$WRAPUP_DIR/lib.sh"

# 本机可做的干跑与 o69_ 前缀模拟。不碰 o53/o55/o57/o60/o61 容器本身，不 drop 它们的已有库，不删匿名卷。
# 用法：selftest-local.sh [--apply]   # 默认只 bash -n / 脚本 dry-run；--apply 才建 o69_ 临时卷和库并在结束时删除
usage() { echo "用法：selftest-local.sh [--apply]"; }
wrapup_parse_common "$@" || { [ $? -eq 99 ] && usage && exit 0; exit 1; }

SC="${SHELLCHECK_BIN:-/workspace/.ops-tools/shellcheck-0.10.0/shellcheck}"
fail=0
wrapup_log "模式=$(wrapup_mode)。本机自检开始"

scripts=()
for f in "$WRAPUP_DIR"/*.sh; do
  scripts+=("$f")
  if ! bash -n "$f"; then
    wrapup_log "bash -n 失败：$f"
    fail=1
  fi
done
if [ -x "$SC" ]; then
  if ! (cd "$WRAPUP_DIR" && "$SC" -s bash -x ./*.sh); then
    wrapup_log "shellcheck 失败"
    fail=1
  else
    wrapup_log "shellcheck 通过"
  fi
else
  wrapup_log "WARN: 找不到 shellcheck（$SC），已做 bash -n"
fi
wrapup_log "bash -n 已跑完 ${#scripts[@]} 个脚本"

# 各子命令 dry-run（不 compose up、不 fetch）
"$WRAPUP_DIR/wrapup.sh" preflight --target "$WRAPUP_TARGET" || fail=1
"$WRAPUP_DIR/backup.sh" --volume-prefix o69 || fail=1
"$WRAPUP_DIR/update-repo.sh" --target "$(git -C "$AIA_ROOT" rev-parse HEAD)" || fail=1
"$WRAPUP_DIR/start-stack.sh" || fail=1
"$WRAPUP_DIR/halt-check.sh" --volume o69_ingest_state || fail=1
"$WRAPUP_DIR/net-verify.sh" || fail=1
"$WRAPUP_DIR/verify.sh" --volume-prefix o69 || fail=1

if [ "$WRAPUP_APPLY" -eq 0 ]; then
  [ "$fail" -eq 0 ] || wrapup_die "dry-run 自检有失败"
  wrapup_log "dry-run 自检通过。加 --apply 才会创建并清理 o69_ 临时卷/库。"
  exit 0
fi

cleanup() {
  set +e
  wrapup_log "清理 o69_ 临时资源（不碰受保护实例）"
  if command -v psql >/dev/null; then
    for db in o69_wrapup_src o69_wrapup_dst o69_rollback_dst; do
      psql -h 127.0.0.1 -p 55461 -U postgres -d postgres -v ON_ERROR_STOP=1 \
        -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$db' AND pid<>pg_backend_pid();" >/dev/null 2>&1
      psql -h 127.0.0.1 -p 55461 -U postgres -d postgres -v ON_ERROR_STOP=1 \
        -c "DROP DATABASE IF EXISTS $db;" >/dev/null 2>&1
    done
  fi
  for c in $(wrapup_docker ps -aq --filter "name=o69_" 2>/dev/null); do
    wrapup_docker rm -f "$c" >/dev/null 2>&1
  done
  for v in $(wrapup_docker volume ls -q 2>/dev/null | grep -E '^o69_' || true); do
    wrapup_assert_temp_volume "$v"
    wrapup_docker volume rm "$v" >/dev/null 2>&1 || wrapup_log "WARN: 未能删除临时卷 $v"
  done
  rm -rf "$WRAPUP_BACKUP_DIR"
  set -e
}
trap cleanup EXIT

# ---- HALT 目录 ----
wrapup_docker volume create o69_ingest_state >/dev/null
wrapup_assert_temp_volume o69_ingest_state
set +e
"$WRAPUP_DIR/halt-check.sh" --apply --volume o69_ingest_state
hrc=$?
set -e
if [ "$hrc" -eq 78 ]; then
  wrapup_log "未修复前探测退出 78，符合预期"
else
  wrapup_log "ERROR: 空卷探测期望 78，实际 $hrc"
  fail=1
fi
"$WRAPUP_DIR/halt-check.sh" --apply --repair --volume o69_ingest_state
"$WRAPUP_DIR/halt-check.sh" --apply --volume o69_ingest_state
wrapup_log "修复后 halt 探测通过"

# ---- 收据卷快照/恢复 ----
wrapup_docker volume create o69_aia_receipts >/dev/null
wrapup_docker run --rm --network none --user 0 -v o69_aia_receipts:/run/aia/receipts alpine:3.21 \
  sh -c 'install -d -o root -g root -m 0755 /run/aia/receipts
    echo "{\"kind\":\"fictional-receipt\"}" > /run/aia/receipts/probe.json
    chown root:root /run/aia/receipts/probe.json
    chmod 0644 /run/aia/receipts/probe.json'
WORKDIR_BACKUP="$WRAPUP_DIR/../../../deploy/backups/wrapup-selftest-$$"
# 用独立目录，避免污染默认 backups
WRAPUP_BACKUP_DIR="$WORKDIR_BACKUP"
export AIA_WRAPUP_BACKUP_DIR="$WORKDIR_BACKUP"

# ---- 库 dump / restore ----
wrapup_assert_temp_db_name o69_wrapup_src
wrapup_assert_temp_db_name o69_wrapup_dst
psql -h 127.0.0.1 -p 55461 -U postgres -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS o69_wrapup_src;"
psql -h 127.0.0.1 -p 55461 -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE o69_wrapup_src;"
psql -h 127.0.0.1 -p 55461 -U postgres -d o69_wrapup_src -v ON_ERROR_STOP=1 -c \
  "CREATE TABLE wrapup_probe(id int PRIMARY KEY, note text); INSERT INTO wrapup_probe VALUES (1, 'o69-selftest');"

"$WRAPUP_DIR/backup.sh" --apply --volume-prefix o69 --container o61-pg --db o69_wrapup_src --backup-dir "$WORKDIR_BACKUP"
bdir="$(ls -1d "$WORKDIR_BACKUP"/20* | tail -1)"
[ -d "$bdir" ] || wrapup_die "没有备份目录"
dump="$(ls -1 "$bdir"/*.dump | head -1)"
wrapup_pg_restore_to o61-pg "$dump" o69_wrapup_dst
got="$(psql -h 127.0.0.1 -p 55461 -U postgres -d o69_wrapup_dst -Atc "SELECT note FROM wrapup_probe WHERE id=1;")"
if [ "$got" = "o69-selftest" ]; then
  wrapup_log "pg_dump/恢复核对通过"
else
  wrapup_log "ERROR: 恢复后读到的不是探测行（不打印查询细节）"
  fail=1
fi

# 卷快照里应有 receipts
if [ -f "$bdir/aia_receipts.tgz" ]; then
  wrapup_docker volume create o69_aia_receipts_restored >/dev/null
  wrapup_docker run --rm --network none -v o69_aia_receipts_restored:/v -v "$bdir:/in:ro" alpine:3.21 \
    sh -c 'tar -C /v -xzf /in/aia_receipts.tgz && test -f /v/probe.json'
  wrapup_log "收据卷快照恢复通过"
else
  wrapup_log "ERROR: 备份中没有 aia_receipts.tgz"
  fail=1
fi

# 确认受保护库仍在
still="$(psql -h 127.0.0.1 -p 55461 -U postgres -d postgres -Atc "SELECT datname FROM pg_database WHERE datname IN ('o61_tmp_0030','tt51_tpl') ORDER BY 1;")"
wrapup_log "受保护库仍在（名字）：$(printf '%s' "$still" | tr '\n' ' ')"

[ "$fail" -eq 0 ] || wrapup_die "自检有失败项；trap 仍会清理 o69_ 资源"
wrapup_log "selftest --apply 通过，开始清理"
