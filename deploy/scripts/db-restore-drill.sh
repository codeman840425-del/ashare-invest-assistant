#!/usr/bin/env bash
# 备份/恢复演练（可重复执行；全程使用临时容器与临时库，绝不连接 aia 主库）。
#   deploy/scripts/db-restore-drill.sh
#   AIA_DRILL_SECURITIES=50 AIA_DRILL_DAYS=20 deploy/scripts/db-restore-drill.sh
# 流程：起源容器（与 compose 相同的固定镜像 + 同一份 postgresql.conf，内存参数调小）
#   → 建演练库 aia_drill + 样例表（deploy/db/drill/）→ db-apply-timescale.sh 应用策略
#   → 灌样例数据 → 跑压缩作业 → 刷新连续聚合 → db-backup.sh
#   → 起全新目标容器 → db-restore.sh 恢复到 aia_drill_restored
#   → 校验：各表行数、逐行 md5、压缩 chunk 数、连续聚合可查询且可继续刷新、策略作业齐全
#   → 结果写 deploy/drills/<UTC时间>-restore-drill.{md,json}；删除容器、卷与 dump。
# 环境变量：AIA_PG_IMAGE（默认取 compose 中 postgres 的镜像）、AIA_DRILL_SECURITIES（50）、
#           AIA_DRILL_DAYS（20 个交易日）、AIA_DRILL_KEEP=1（保留容器与 dump 以便排查）
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
IMAGE="${AIA_PG_IMAGE:-$(aia_compose_image postgres)}"
SECURITIES="${AIA_DRILL_SECURITIES:-50}"; DAYS="${AIA_DRILL_DAYS:-20}"
SRC="aia-drill-src-${RUN_ID,,}"; DST="aia-drill-dst-${RUN_ID,,}"
SRC_DB=aia_drill; DST_DB=aia_drill_restored
WORK="$(mktemp -d /tmp/aia-drill-XXXXXX)"
OUT_DIR="$AIA_ROOT/deploy/drills"; mkdir -p "$OUT_DIR"
REPORT_MD="$OUT_DIR/$RUN_ID-restore-drill.md"; REPORT_JSON="$OUT_DIR/$RUN_ID-restore-drill.json"
DRILL_SQL="$AIA_ROOT/deploy/db/drill"
CONF="$AIA_ROOT/deploy/postgres/conf/postgresql.conf"
T0=$(date +%s)
declare -A STEP_SECS

cleanup() {
  local rc=$?
  if [ $rc -ne 0 ] && [ ! -f "$REPORT_MD" ]; then   # 中途失败也留下记录
    { echo "# 备份/恢复演练 $RUN_ID — FAIL"; echo; echo "- 镜像：\`$IMAGE\`"; echo "- 失败步骤：${STEP_NAME:-?}（退出码 $rc）"
      echo "- 详见执行输出；AIA_DRILL_KEEP=1 可保留现场"; } >"$REPORT_MD"
    printf '{"run_id": "%s", "result": "FAIL", "failed_step": "%s", "exit_code": %d}\n' "$RUN_ID" "${STEP_NAME:-?}" "$rc" >"$REPORT_JSON"
    aia_log "结果：FAIL（步骤 ${STEP_NAME:-?}）→ ${REPORT_MD#$AIA_ROOT/}"
  fi
  if [ "${AIA_DRILL_KEEP:-0}" = "1" ]; then aia_log "AIA_DRILL_KEEP=1：保留 $SRC $DST 与 $WORK"; return; fi
  aia_docker rm -fv "$SRC" "$DST" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

step() { STEP_NAME="$1"; STEP_START=$(date +%s); aia_log "== $1"; }
done_step() { STEP_SECS["$STEP_NAME"]=$(( $(date +%s) - STEP_START )); }

start_pg() {  # $1 容器名
  local pw; pw="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
  aia_docker run -d --name "$1" --label aia.drill="$RUN_ID" --shm-size 256m \
    -e POSTGRES_PASSWORD="$pw" -e POSTGRES_USER=aia -e POSTGRES_DB=postgres -e TZ=UTC \
    -v "$CONF:/etc/postgresql/postgresql.conf:ro" \
    "$IMAGE" postgres -c config_file=/etc/postgresql/postgresql.conf \
      -c shared_buffers=256MB -c effective_cache_size=1GB -c maintenance_work_mem=256MB -c max_wal_size=1GB >/dev/null
  local i
  for i in $(seq 1 90); do
    # 初始化阶段只监听 unix socket；TCP 可连即为正式启动后的实例
    if aia_docker exec "$1" pg_isready -q -h 127.0.0.1 -U aia -d postgres 2>/dev/null; then return 0; fi
    sleep 1
  done
  aia_docker logs "$1" 2>&1 | tail -20 >&2; aia_die "$1 未在 90s 内就绪"
}
psql_in() { local c="$1" db="$2"; shift 2; aia_psql "$c" "$db" -q "$@"; }
metrics() { psql_in "$1" "$2" -tA -F '=' <"$DRILL_SQL/metrics.sql"; }

aia_log "演练 $RUN_ID：镜像 $IMAGE，样例 ${SECURITIES} 只 × ${DAYS} 个交易日 × 240 根"

step "start-source";  start_pg "$SRC"; done_step
step "seed"
psql_in "$SRC" postgres -c "CREATE DATABASE $SRC_DB"
psql_in "$SRC" "$SRC_DB" -c "SET client_min_messages = warning; CREATE EXTENSION IF NOT EXISTS timescaledb"
psql_in "$SRC" "$SRC_DB" <"$DRILL_SQL/sample-schema.sql"
APPLY_LOG="$WORK/apply.log"
"$AIA_ROOT/deploy/scripts/db-apply-timescale.sh" --container "$SRC" --db "$SRC_DB" >"$APPLY_LOG" 2>&1 || { cat "$APPLY_LOG" >&2; aia_die "策略应用失败"; }
APPLY2_LOG="$WORK/apply2.log"   # 第二次应用应全部 OK（幂等）
"$AIA_ROOT/deploy/scripts/db-apply-timescale.sh" --container "$SRC" --db "$SRC_DB" >"$APPLY2_LOG" 2>&1 || { cat "$APPLY2_LOG" >&2; aia_die "策略二次应用失败"; }
APPLY_CHANGES_2ND="$(grep -c 'NOTICE: \[aia-ts\]' "$APPLY2_LOG" | tr -d ' ')"
APPLY_NONOK_2ND="$(grep 'NOTICE: \[aia-ts\]' "$APPLY2_LOG" | grep -vcE ' OK|SKIP' | tr -d ' ' || true)"
psql_in "$SRC" "$SRC_DB" -v securities="$SECURITIES" -v days="$DAYS" <"$DRILL_SQL/sample-data.sql"
done_step

step "compress+cagg"
COMPRESS_OUT="$(psql_in "$SRC" "$SRC_DB" -tA -F '=' <<'SQL'
SELECT job_id AS j1 FROM timescaledb_information.jobs WHERE proc_name='policy_compression' AND hypertable_name='minute_bars' \gset
SELECT job_id AS j2 FROM timescaledb_information.jobs WHERE proc_name='policy_compression' AND hypertable_name='realtime_quotes' \gset
CALL run_job(:j1);
CALL run_job(:j2);
CALL refresh_continuous_aggregate('market.bars_5m', NULL, now() - interval '5 minutes');
CALL refresh_continuous_aggregate('market.bars_daily_from_1m', NULL, now() - interval '1 hour');
SELECT 'minute_bars.before_bytes', sum(before_compression_total_bytes) FROM chunk_compression_stats('market.minute_bars') WHERE compression_status = 'Compressed'
UNION ALL SELECT 'minute_bars.after_bytes', sum(after_compression_total_bytes) FROM chunk_compression_stats('market.minute_bars') WHERE compression_status = 'Compressed'
UNION ALL SELECT 'minute_bars.uncompressed_rows_per_chunk_bytes', (SELECT round(avg(total_bytes)) FROM chunks_detailed_size('market.minute_bars') c
   JOIN timescaledb_information.chunks i ON i.chunk_name = c.chunk_name AND NOT i.is_compressed)
UNION ALL SELECT 'minute_bars.hypertable_bytes', hypertable_size('market.minute_bars');
SQL
)"
done_step
metrics "$SRC" "$SRC_DB" >"$WORK/src.metrics"

step "backup"
DUMP="$("$AIA_ROOT/deploy/scripts/db-backup.sh" --container "$SRC" --db "$SRC_DB" --out-dir "$WORK" | tail -n1)"
DUMP_SIZE=$(stat -c %s "$DUMP"); DUMP_SHA=$(sha256sum "$DUMP" | cut -d' ' -f1)
done_step

step "start-target"; start_pg "$DST"; done_step
step "restore"
"$AIA_ROOT/deploy/scripts/db-restore.sh" "$DUMP" --container "$DST" --db "$DST_DB"
done_step

step "verify"
metrics "$DST" "$DST_DB" >"$WORK/dst.metrics"
# 恢复后：连续聚合可查询、可继续刷新；策略作业仍可执行（手动跑一次保留作业不应删除演练数据）
POST_OUT="$(psql_in "$DST" "$DST_DB" -tA -F '=' <<'SQL'
SELECT 'cagg.query.bars_5m', count(*) FROM (SELECT * FROM market.bars_5m WHERE security_id = 1 ORDER BY bucket DESC LIMIT 10) s;
CALL refresh_continuous_aggregate('market.bars_5m', NULL, now() - interval '5 minutes');
SELECT 'cagg.refresh_after_restore', 'ok';
SELECT job_id AS rj FROM timescaledb_information.jobs WHERE proc_name='policy_retention' AND hypertable_name='minute_bars' \gset
CALL run_job(:rj);
SELECT 'job.run_after_restore.minute_bars_retention', 'ok';
SELECT 'compressed_range_readable', count(*) FROM (
  SELECT 1 FROM market.minute_bars WHERE security_id = 1 AND ts < now() - interval '8 days' LIMIT 1) s;
SELECT 'timescaledb.restoring', current_setting('timescaledb.restoring', true);
SQL
)"
done_step

# --- 比对 ---
PASS=1; CHECKS=""
while IFS='=' read -r k v; do
  dv="$(grep -m1 "^${k}=" "$WORK/dst.metrics" | cut -d= -f2- || true)"
  if [ "$v" = "$dv" ]; then r=PASS; else r=FAIL; PASS=0; fi
  CHECKS+="$k"$'\t'"$v"$'\t'"$dv"$'\t'"$r"$'\n'
done <"$WORK/src.metrics"
getm() { grep -m1 "^$1=" "$2" | cut -d= -f2-; }
COMP_CHUNKS="$(getm chunks.compressed "$WORK/dst.metrics")"
[ "${COMP_CHUNKS:-0}" -gt 0 ] || { PASS=0; aia_log "恢复库没有压缩 chunk"; }
[ "$(getm jobs.count "$WORK/dst.metrics")" -ge 9 ] || { PASS=0; aia_log "恢复库策略作业不足 9 个"; }
grep -q '^cagg.refresh_after_restore=ok' <<<"$POST_OUT" || PASS=0
[ "${APPLY_NONOK_2ND:-0}" = "0" ] || { PASS=0; aia_log "第二次 apply 仍有改动（非幂等）"; }
SRC_VER="$(aia_psql "$SRC" "$SRC_DB" -qtA -c "select current_setting('server_version') || ' / timescaledb ' || extversion from pg_extension where extname='timescaledb'")"
DST_VER="$(aia_psql "$DST" "$DST_DB" -qtA -c "select current_setting('server_version') || ' / timescaledb ' || extversion from pg_extension where extname='timescaledb'")"
cv() { grep -m1 "^$1=" <<<"$COMPRESS_OUT" | cut -d= -f2-; }
BEFORE=$(cv minute_bars.before_bytes); AFTER=$(cv minute_bars.after_bytes)
RATIO="$(awk -v b="$BEFORE" -v a="$AFTER" 'BEGIN{ if (a>0) printf "%.1f", b/a; else print "n/a" }')"
ROWS_1M="$(getm rows.market.minute_bars "$WORK/src.metrics")"
TOTAL=$(( $(date +%s) - T0 ))
RESULT=$([ "$PASS" -eq 1 ] && echo PASS || echo FAIL)

# --- 写结果 ---
{
  echo "# 备份/恢复演练 $RUN_ID — $RESULT"
  echo
  echo "- 镜像：\`$IMAGE\`"
  echo "- 源：临时容器 \`$SRC\` 库 \`$SRC_DB\`（$SRC_VER）"
  echo "- 目标：全新临时容器 \`$DST\` 库 \`$DST_DB\`（$DST_VER）"
  echo "- 样例规模：${SECURITIES} 只 × ${DAYS} 个交易日 × 240 根 = ${ROWS_1M} 行 1 分钟 K"
  echo "- dump：pg_dump -Fc，$(numfmt --to=iec "$DUMP_SIZE")，sha256 \`${DUMP_SHA:0:16}…\`（演练结束已删除，未入库）"
  echo "- minute_bars 压缩：压缩前 $(numfmt --to=iec "${BEFORE:-0}") → 压缩后 $(numfmt --to=iec "${AFTER:-0}")，压缩比 ${RATIO}×（$(getm chunks.compressed.minute_bars "$WORK/src.metrics") 个 chunk）"
  echo "- 策略二次应用：${APPLY_CHANGES_2ND} 条输出，非 OK/SKIP 改动 ${APPLY_NONOK_2ND:-0} 条（幂等）"
  echo "- 总耗时：${TOTAL}s（$(for s in start-source seed compress+cagg backup start-target restore verify; do printf '%s %ss; ' "$s" "${STEP_SECS[$s]:-?}"; done)）"
  echo
  echo "## 源库 vs 恢复库"
  echo
  echo "| 检查项 | 源库 | 恢复库 | 结果 |"
  echo "|---|---|---|---|"
  printf '%s' "$CHECKS" | awk -F'\t' 'NF { v=$2; d=$3; if (length(v) > 60) { v = substr(v,1,57) "…"; d = substr(d,1,57) "…" } printf "| %s | %s | %s | %s |\n", $1, v, d, $4 }'
  echo
  echo "## 恢复后功能检查"
  echo
  printf '%s\n' "$POST_OUT" | awk -F'=' 'NF { printf "- %s：%s\n", $1, $2 }'
  echo
  echo "## 策略作业（恢复库）"
  echo
  getm jobs "$WORK/dst.metrics" | tr ';' '\n' | sed 's/^ */- `/; s/ *$/`/'
} >"$REPORT_MD"

python3 - "$REPORT_JSON" "$WORK/src.metrics" "$WORK/dst.metrics" <<PY
import json, sys
def load(p):
    d = {}
    for line in open(p):
        line = line.rstrip("\n")
        if "=" in line:
            k, v = line.split("=", 1); d[k] = v
    return d
src, dst = load(sys.argv[2]), load(sys.argv[3])
json.dump({
  "run_id": "$RUN_ID", "result": "$RESULT", "image": "$IMAGE",
  "source": {"container": "$SRC", "db": "$SRC_DB", "version": "$SRC_VER"},
  "target": {"container": "$DST", "db": "$DST_DB", "version": "$DST_VER"},
  "sample": {"securities": $SECURITIES, "trading_days": $DAYS, "minute_rows": int("$ROWS_1M" or 0)},
  "dump": {"size_bytes": $DUMP_SIZE, "sha256": "$DUMP_SHA", "kept": False},
  "compression": {"minute_bars_before_bytes": int("${BEFORE:-0}" or 0), "minute_bars_after_bytes": int("${AFTER:-0}" or 0), "ratio": "$RATIO"},
  "apply_second_run_non_ok_changes": int("${APPLY_NONOK_2ND:-0}" or 0),
  "duration_seconds": $TOTAL,
  "checks": {k: {"source": v, "restored": dst.get(k), "pass": v == dst.get(k)} for k, v in src.items()},
}, open(sys.argv[1], "w"), ensure_ascii=False, indent=2)
PY
aia_log "结果：$RESULT → ${REPORT_MD#$AIA_ROOT/}"
[ "$PASS" -eq 1 ]
