#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2016
# shellcheck source=lib.sh
{ set +x; } 2>/dev/null
set -euo pipefail
WRAPUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck disable=SC1091
# shellcheck disable=SC2016
. "$WRAPUP_DIR/lib.sh"

usage() { echo "用法：verify.sh [--apply]   # verify-roles 会写探针行并回滚，需要 --apply；其余只读项 dry-run 也会尝试（栈须已启动）"; }
wrapup_parse_common "$@" || { [ $? -eq 99 ] && usage && exit 0; exit 1; }

fail=0
wrapup_log "模式=$(wrapup_mode)"

# alembic 单 head（只读）
if "$COMPOSE" ps -q postgres >/dev/null 2>&1 && [ -n "$("$COMPOSE" ps -q postgres 2>/dev/null || true)" ]; then
  heads="$("$COMPOSE" run --rm --no-deps --entrypoint alembic migrate heads 2>/dev/null | tr -d '\r' || true)"
  current="$("$COMPOSE" run --rm --no-deps --entrypoint alembic migrate current 2>/dev/null | tr -d '\r' || true)"
  # 只打印 revision 行，避免把无关日志里的敏感插值带出
  wrapup_log "alembic heads："
  printf '%s\n' "$heads" | awk '/^[0-9a-zA-Z_]+/ {print "  " $0}' >&2
  wrapup_log "alembic current："
  printf '%s\n' "$current" | awk '/^[0-9a-zA-Z_]+/ {print "  " $0}' >&2
  n="$(printf '%s\n' "$heads" | awk '/^\S+ \(head\)/ || / \(head\)$/ {c++} END{print c+0}')"
  if [ "$n" != "1" ]; then
    # 再试：非空行数
    n="$(printf '%s\n' "$heads" | sed '/^$/d' | wc -l | tr -d ' ')"
  fi
  if [ "$n" != "1" ]; then
    wrapup_log "ERROR: alembic 不是单一 head（计到 $n）"
    fail=1
  else
    wrapup_log "alembic 单一 head，通过"
  fi
else
  wrapup_log "postgres 未运行，跳过 alembic（部署当天栈起来后再跑）"
  [ "$WRAPUP_APPLY" -eq 0 ] || fail=1
fi

# 健康检查
for path in /health/live /login /; do
  code="$(curl -sS -m 5 --noproxy '*' -o /dev/null -w '%{http_code}' "http://127.0.0.1:${NGINX_HTTP_PORT:-8080}${path}" || true)"
  wrapup_log "GET $path -> $code"
  case "$path" in
    /health/live)
      if [ "$code" = "200" ]; then
        :
      elif [ "$WRAPUP_APPLY" -eq 0 ]; then
        wrapup_log "dry-run：本机未监听 8080，跳过健康检查（收口当天栈起来后再验）"
      else
        wrapup_log "ERROR: /health/live 应为 200"
        fail=1
      fi
      ;;
  esac
done

# 收据卷
prefix=""
if prefix="$(wrapup_prefix 2>/dev/null)"; then
  vol="${prefix}_aia_receipts"
  if wrapup_docker volume inspect "$vol" >/dev/null 2>&1; then
    wrapup_log "收据卷 $vol："
    wrapup_docker run --rm --network none --user 0 -v "$vol:/run/aia/receipts:ro" alpine:3.21 \
      sh -c 'echo "dir $(stat -c "%U:%G %a %n" /run/aia/receipts)"; ls -la /run/aia/receipts' || fail=1
    wrapup_log "期望目录 root:root 755；文件 root:root 644。只删收据不能恢复出口（receipts.md）。"
  else
    wrapup_log "收据卷 $vol 尚不存在"
  fi
else
  wrapup_log "未解析卷前缀，跳过收据卷检查"
fi

# verify-roles 会插入探针用户并清理，必须 --apply
if [ "$WRAPUP_APPLY" -eq 0 ]; then
  wrapup_log "dry-run：不跑 verify-roles.sh（它会写探针行）。验收要求输出 OK、FAIL 0、SKIP 0。--apply 时执行。"
else
  wrapup_log "运行 verify-roles.sh"
  tmp="$(mktemp)"
  set +e
  "$COMPOSE" run --rm --no-deps --entrypoint bash db-roles /aia/deploy/db/roles/verify-roles.sh >"$tmp" 2>&1
  vrc=$?
  set -e
  # 不把可能含 SQL 细节的全文无过滤地打出；只汇总 OK/FAIL/SKIP 行数
  ok_n="$(grep -c '^OK' "$tmp" || true)"
  fail_n="$(grep -c '^FAIL' "$tmp" || true)"
  skip_n="$(grep -c '^SKIP' "$tmp" || true)"
  wrapup_log "verify-roles rc=$vrc OK=$ok_n FAIL=$fail_n SKIP=$skip_n"
  if [ "$vrc" -ne 0 ] || [ "$fail_n" != "0" ] || [ "$skip_n" != "0" ]; then
    wrapup_log "ERROR: 未达到 OK 且 FAIL 0、SKIP 0"
    grep '^FAIL' "$tmp" | wrapup_redact >&2 || true
    fail=1
  else
    wrapup_log "verify-roles 通过"
  fi
  rm -f "$tmp"
fi

if [ "$fail" -ne 0 ]; then
  wrapup_die "验收未通过"
fi
wrapup_log "验收项通过（dry-run 时 verify-roles 尚未跑）。"
