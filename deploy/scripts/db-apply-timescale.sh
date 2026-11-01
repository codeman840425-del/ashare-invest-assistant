#!/usr/bin/env bash
# 按 deploy/db/timescale/policies.conf 应用 TimescaleDB 部署侧策略（幂等，可反复执行）。
#   deploy/scripts/db-apply-timescale.sh                 # 对 compose 的 postgres 容器、POSTGRES_DB 库执行
#   deploy/scripts/db-apply-timescale.sh --dry-run       # 只打印将要做的改动
#   deploy/scripts/db-apply-timescale.sh --db aia_drill --container <名字>   # 指定库/容器（演练用）
#   deploy/scripts/db-apply-timescale.sh --only market.minute_bars
# 环境变量：AIA_PG_CONTAINER、AIA_TS_POLICY_FILE（默认 deploy/db/timescale/policies.conf）、
#           AIA_TS_MIGRATE_DATA=1（允许把已有数据的普通表转换为 hypertable，会锁表并复制数据）、
#           AIA_TS_KEY_COLS（连续聚合的证券列候选，默认 security_id/code）
# 表不存在时打印 SKIP 并继续；任何一项 SQL 出错时该项失败、其余照常执行，最终退出码 1。
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

TS_DIR="$AIA_ROOT/deploy/db/timescale"
CONF="${AIA_TS_POLICY_FILE:-$TS_DIR/policies.conf}"
DB=""; CONTAINER="${AIA_PG_CONTAINER:-}"; DRY=0; ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB="$2"; shift 2 ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --only) ONLY="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) aia_die "未知参数：$1" ;;
  esac
done
[ -f "$CONF" ] || aia_die "找不到策略文件 $CONF"
[ -n "$CONTAINER" ] || CONTAINER="$(aia_pg_container)"
if [ -z "$DB" ]; then DB="$(aia_docker exec "$CONTAINER" sh -c 'printf %s "$POSTGRES_DB"')"; fi
[ -n "$DB" ] || aia_die "无法确定目标库（--db）"

aia_psql "$CONTAINER" "$DB" -qtAc "select 1 from pg_extension where extname='timescaledb'" | grep -q 1 \
  || aia_die "库 $DB 未安装 timescaledb 扩展"
aia_log "目标：容器 ${CONTAINER:0:12} 库 $DB；策略文件 ${CONF#$AIA_ROOT/}；dry-run=$DRY"

trim() { local s="$1"; s="${s#"${s%%[![:space:]]*}"}"; s="${s%"${s##*[![:space:]]}"}"; printf '%s' "$s"; }
FAIL=0; N=0
run_item() {  # $1 = SQL 模板，其余为 psql -v 参数
  local tpl="$1"; shift
  local out rc=0
  out="$(cat "$TS_DIR/sql/00-functions.sql" "$TS_DIR/sql/$tpl" \
         | aia_psql "$CONTAINER" "$DB" -q -v dry_run="$DRY" "$@" 2>&1)" || rc=$?
  printf '%s\n' "$out" | sed -n 's/^.*\(NOTICE\|WARNING\|ERROR\):  /  \1: /p'
  if [ $rc -ne 0 ]; then FAIL=$((FAIL + 1)); printf '%s\n' "$out" | grep -v '^NOTICE' | sed 's/^/  | /' >&2; fi
}

while IFS= read -r line || [ -n "$line" ]; do
  line="$(trim "${line%%#*}")"; [ -n "$line" ] || continue
  IFS='|' read -r -a f <<<"$line"
  for i in "${!f[@]}"; do f[$i]="$(trim "${f[$i]}")"; done
  [ -z "$ONLY" ] || [ "${f[1]}" = "$ONLY" ] || continue
  N=$((N + 1))
  case "${f[0]}" in
    hypertable)
      [ "${#f[@]}" -eq 8 ] || aia_die "格式错误（hypertable 需 8 个字段）：$line"
      run_item 10-hypertable.sql -v tbl="${f[1]}" -v time_col="${f[2]}" -v chunk="${f[3]}" \
        -v segmentby="${f[4]}" -v orderby="${f[5]}" -v compress_after="${f[6]}" -v drop_after="${f[7]}" \
        -v migrate="${AIA_TS_MIGRATE_DATA:-0}" ;;
    cagg)
      [ "${#f[@]}" -eq 9 ] || aia_die "格式错误（cagg 需 9 个字段）：$line"
      def_file="$TS_DIR/caggs/${f[3]}"; [ -f "$def_file" ] || aia_die "找不到连续聚合定义 $def_file"
      def="$(grep -v '^[[:space:]]*--' "$def_file")"
      run_item 20-cagg.sql -v cagg="${f[1]}" -v source="${f[2]}" -v def="$def" \
        -v key_alts="${AIA_TS_KEY_COLS:-security_id/code}" -v start_offset="${f[4]}" -v end_offset="${f[5]}" \
        -v schedule="${f[6]}" -v compress_after="${f[7]}" -v drop_after="${f[8]}" ;;
    *) aia_die "未知类型 ${f[0]}：$line" ;;
  esac
done <"$CONF"

aia_log "当前 TimescaleDB 策略作业："
aia_psql "$CONTAINER" "$DB" -q -P pager=off -c "
  select job_id, proc_name, hypertable_schema || '.' || hypertable_name as target, schedule_interval,
         coalesce(config->>'compress_after', config->>'drop_after',
                  (config->>'start_offset') || ' .. ' || (config->>'end_offset')) as param
  from timescaledb_information.jobs where hypertable_name is not null order by 3, 2" >&2
if [ "$FAIL" -gt 0 ]; then aia_log "完成：$N 项，失败 $FAIL 项"; exit 1; fi
aia_log "完成：$N 项，全部成功（SKIP 项见上）"
