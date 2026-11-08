#!/bin/sh
# T-B81 临时证书文件守卫（T-O23）。路径来自 probes/tb81.py 的 SECRET。
# 只做 lstat 检查。不打开、不跟随、不 shred、不删除，因此不会覆写软链目标，
# 也不会在路径被替换时碰到别的文件。发现目录项则退出 4，调用方必须停手。
# 自测可传第二个参数指向临时路径；正式运行不要传。
set -eu
umask 077
cmd=${1:-}
path=${2:-/workspace/team/runtime/mairui-T-B81.tmp}
dir=$(dirname "$path")
case "$path" in
  /*) ;;
  *) echo "tb81-guard: 路径必须是绝对路径" >&2; exit 2 ;;
esac
case "$cmd" in
  before|after) ;;
  *) echo "用法: $0 before|after [仅自测用的绝对路径]" >&2; exit 2 ;;
esac
if [ ! -d "$dir" ]; then
  if [ "$cmd" != before ]; then
    echo "tb81-guard: 私有目录不存在，停止" >&2
    exit 2
  fi
  mkdir -m 0700 -p "$dir"
fi
mode=$(stat -c '%a' "$dir")
owner=$(stat -c '%u' "$dir")
if [ "$mode" != 700 ] || [ "$owner" != "$(id -u)" ]; then
  echo "tb81-guard: 私有目录权限或属主不对（要求 0700 且属主为当前用户），停止。不显示目录内容。" >&2
  exit 2
fi
# stat 默认不跟随最后一级。目录项存在（含悬空软链、特殊文件、异主文件）即停，不读取内容。
if stat --printf= -- "$path" >/dev/null 2>&1; then
  echo "tb81-guard: 临时路径在 ${cmd} 检查时有目录项，已停止。不打开、不删除、不显示内容。" >&2
  exit 4
fi
echo "tb81-guard: ${cmd} 检查通过，临时证书文件不存在"
