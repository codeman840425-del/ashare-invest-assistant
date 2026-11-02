#!/usr/bin/env bash
# 迁移 0017（T-B49：data_snapshots 用户级快照必须带 user_id）升级前预检查。只读，不改数据。
# 架构师要求（review-6670b10）：任何共享库升级到 0017 之前先查违规行；查到就停下，不跑 0017，人工处理后再升级。
#   db-precheck-0017.sh [--container C] [--db NAME]
# 退出码：0 = 可以升级（无违规行 / 空库 / 已在 0017 或之后）；1 = 有违规行，停止；2 = 用法或查询出错。
# SQL 与 src/backend/migrations/versions/0017_t_b49_snapshot_purpose.py 的 PRECHECK_SQL 一致（测试守着）。
# 只输出 purpose 和行数，不输出任何用户数据。up.sh 在 postgres 已运行时自动调用本脚本。
{ set +x; } 2>/dev/null
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$HERE/lib/common.sh"

PRECHECK_SQL="SELECT purpose, count(*) AS n FROM app.data_snapshots WHERE purpose IN ('candidate', 'plan', 'horizon') AND user_id IS NULL GROUP BY purpose ORDER BY purpose"

CONTAINER=""; DB=""
while [ $# -gt 0 ]; do
  case "$1" in
    --container) CONTAINER="${2:?--container 需要参数}"; shift 2 ;;
    --db) DB="${2:?--db 需要参数}"; shift 2 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done
[ -n "$CONTAINER" ] || CONTAINER="$(aia_pg_container)"
if [ -z "$DB" ]; then
  if aia_psql_direct; then DB="${PGDATABASE:-postgres}"
  else DB="$(aia_docker exec "$CONTAINER" sh -c 'printf %s "${POSTGRES_DB:-postgres}"')"; fi
fi

q() { aia_psql "$CONTAINER" "$DB" -q -At -F '=' || { aia_log "预检查查询失败"; exit 2; }; }

ver="$(printf '%s\n' "BEGIN READ ONLY;" \
  "SELECT CASE WHEN to_regclass('public.alembic_version') IS NULL THEN '' ELSE (SELECT coalesce(max(version_num), '') FROM alembic_version) END;" \
  "ROLLBACK;" | q)"
if [ -z "$ver" ]; then aia_log "0017 预检查：库里还没有迁移记录（空库），无需检查"; exit 0; fi
if [[ "$ver" =~ ^[0-9]+$ ]] && [ "$((10#$ver))" -ge 17 ]; then
  aia_log "0017 预检查：当前迁移版本 $ver，已在 0017 或之后，跳过"; exit 0
fi
has_tbl="$(printf '%s\n' "BEGIN READ ONLY;" "SELECT coalesce(to_regclass('app.data_snapshots')::text, '');" "ROLLBACK;" | q)"
if [ -z "$has_tbl" ]; then aia_log "0017 预检查：app.data_snapshots 不存在（版本 $ver），无需检查"; exit 0; fi

bad="$(printf '%s\n' "BEGIN READ ONLY;" "$PRECHECK_SQL;" "ROLLBACK;" | q)"
if [ -n "$bad" ]; then
  aia_log "0017 预检查失败（当前版本 $ver）：app.data_snapshots 有 user_id 为空的用户级快照：$(printf '%s' "$bad" | tr '\n' ' ')"
  aia_log "停止：不要升级到 0017。按报告 T-B49.md 人工处理（找后端/架构师），处理后重跑本脚本。"
  exit 1
fi
aia_log "0017 预检查通过（当前版本 $ver）：违规行 0"
