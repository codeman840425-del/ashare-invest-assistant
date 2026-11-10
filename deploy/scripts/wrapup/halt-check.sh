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

usage() { echo "用法：halt-check.sh [--apply] [--repair] [--volume VOL | --volume-prefix P]"; }
wrapup_parse_common "$@" || { [ $? -eq 99 ] && usage && exit 0; exit 1; }

# 出处：契约 / T-A91 M-c、T-B116d、src/backend/app/workers/ingest.py:_probe_halt_directory
# 停机目录不可写 → ingest 拒绝启动，退出码 78，文案「停机标志目录不可写」，不碰已有 HALT 文件。

vol="$WRAPUP_VOLUME"
if [ -z "$vol" ]; then
  prefix="$(wrapup_prefix)"
  vol="${prefix}_ingest_state"
fi
wrapup_log "模式=$(wrapup_mode)。检查卷 $vol -> $WRAPUP_HALT_DIR 属主 ${WRAPUP_STATE_UID}、权限 ${WRAPUP_STATE_MODE}"
wrapup_log "出处：docs/api-contract.md（bootstrap 可写探测，不可写 78）；ingest.py:_probe_halt_directory；T-A91 / T-B116d / T-T56 / T-T57。"

if ! wrapup_docker volume inspect "$vol" >/dev/null 2>&1; then
  wrapup_log "卷 $vol 还不存在（未启动过 ingest 时常见）。--apply --repair 可预建属主与权限；dry-run 到此结束。"
  if wrapup_need_apply "创建卷 $vol 并设置 halt 目录 10001/700"; then
    [ "$WRAPUP_REPAIR" -eq 1 ] || wrapup_die "卷不存在。预建请加 --apply --repair（不要 down -v）"
  else
    exit 0
  fi
fi

stat_dir() {
  wrapup_docker run --rm --network none --user 0 -v "$vol:/run/aia/state" alpine:3.21 \
    sh -c 'if [ ! -d /run/aia/state/halt ]; then echo MISSING; exit 0; fi
      stat -c "uid=%u gid=%g mode=%a path=%n" /run/aia/state /run/aia/state/halt'
}

probe_as_user() {
  # 与产品相同：O_EXCL 创建 .probe-<pid> 再删除，不碰已有 HALT。不可写则本脚本退出 78。
  wrapup_docker run --rm --network none --user "${WRAPUP_STATE_UID}:${WRAPUP_STATE_UID}" \
    -v "$vol:/run/aia/state" alpine:3.21 \
    sh -c 'd=/run/aia/state/halt
      if [ ! -d "$d" ]; then echo "停机标志目录不可写"; exit 78; fi
      p="$d/.probe-$$"
      if ! (umask 077; : >"$p"); then echo "停机标志目录不可写"; exit 78; fi
      rm -f "$p"
      echo PROBE_OK'
}

repair() {
  wrapup_docker run --rm --network none --user 0 -v "$vol:/run/aia/state" alpine:3.21 \
    sh -c 'set -e
      install -d -o 10001 -g 10001 -m 700 /run/aia/state /run/aia/state/halt
      chown 10001:10001 /run/aia/state /run/aia/state/halt
      # 不删除已有 HALT 文件；尽量把目录树属主收回到 10001
      chown -R 10001:10001 /run/aia/state
      chmod 700 /run/aia/state /run/aia/state/halt
      echo REPAIR_OK'
}

wrapup_log "当前 stat："
stat_dir | wrapup_redact || wrapup_log "stat 失败（卷可能尚未格式化）"

if [ "$WRAPUP_REPAIR" -eq 1 ]; then
  if wrapup_need_apply "修复 $vol 上 halt 目录为 10001/700（不删已有 HALT）"; then
    repair
    stat_dir
  else
    wrapup_log "dry-run：将以 root 一次性容器 install -d -o 10001 -m 700，并 chown，不删 HALT 文件"
    exit 0
  fi
fi

if [ "$WRAPUP_APPLY" -eq 0 ]; then
  wrapup_log "dry-run：未做 uid 10001 的可写探测。--apply 时将创建并删除 .probe-*（与 ingest 启动探测相同）。不可写则退出 78。"
  exit 0
fi

if out="$(probe_as_user)"; then
  wrapup_log "$out"
  wrapup_log "halt 目录可写，检查通过"
  exit 0
fi
rc=$?
wrapup_log "探测失败 rc=$rc（ingest 在同样情况下会退出 78，文案：停机标志目录不可写）"
wrapup_log "修复：deploy/scripts/wrapup/halt-check.sh --apply --repair --volume $vol"
wrapup_rollback_hint
if [ "$rc" -eq 78 ]; then
  exit 78
fi
exit 78
