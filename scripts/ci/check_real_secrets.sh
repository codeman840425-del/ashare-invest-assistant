#!/usr/bin/env bash
# 真实密钥值精确比对（plan §7.4A S1/S2 “真实值精确匹配”）——只在本机运行，CI 不运行。
# CI 不配置 MAIRUI_LICENCE / DEEPSEEK_API_KEY（麦蕊同一证书 60 秒内最多 2 个公网 IP，GitHub 出口 IP 会触发；
# CI 也不调真实 LLM），所以这项比对挂在 pre-commit（暂存区）和 pre-push（待推送提交）钩子上。
# 值的来源（按变量逐个取）：① 本机环境变量；② 未设置时读 env 文件（默认 <仓库根>/deploy/env/.env，
#   可用 AIA_SECRET_ENV_FILE 指定）。env 文件只做 KEY=VALUE 文本解析，不 source、不执行。
#   空值、含 < 或 > 的占位值、changeme/example 开头的值、短于 8 个字符的值视为未配置。
# 用 git grep -qF 与仓库内容比对。任何情况下都不打印值：值只写进权限 600 的临时模式文件，
# 不出现在命令行参数里；命中只输出 FOUND 和变量名。
# 用法：check_real_secrets.sh [worktree|cached|history|push|RANGE]
#   worktree  已跟踪文件（工作区）      cached   暂存区（pre-commit）
#   history   全部提交（含所有分支）    A..B     区间内每个提交的完整树
#   push      pre-push：PRE_COMMIT_FROM_REF..PRE_COMMIT_TO_REF；没有这两个变量时用 @{upstream}..HEAD，再不行用 origin/main..HEAD
# 退出码：0 未发现；1 发现；两个值都取不到时输出提示并退出 0。
set -euo pipefail
mode="${1:-worktree}"
umask 077
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
root="$(git rev-parse --show-toplevel)"
env_file="${AIA_SECRET_ENV_FILE:-$root/deploy/env/.env}"

# 从 env 文件读取某个键的值（最后一次出现为准），去掉首尾空白和一层成对引号；不 source。
read_env_file() {
  local key="$1" line v="" found=""
  [ -f "$env_file" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
      "$key="* | "export $key="*) v="${line#*"$key="}"; found=1 ;;
    esac
  done < "$env_file"
  [ -n "$found" ] || return 1
  v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"
  case "$v" in
    \"*\") v="${v#\"}"; v="${v%\"}" ;;
    \'*\') v="${v#\'}"; v="${v%\'}" ;;
  esac
  printf '%s' "$v"
}

usable() {
  local v="$1"
  [ "${#v}" -ge 8 ] || return 1
  case "$v" in *"<"* | *">"* | changeme* | example* | CHANGEME*) return 1 ;; esac
  return 0
}

if [ "$mode" = push ]; then
  if [ -n "${PRE_COMMIT_FROM_REF:-}" ] && [ -n "${PRE_COMMIT_TO_REF:-}" ] \
     && ! [[ "$PRE_COMMIT_FROM_REF" =~ ^0+$ ]]; then
    mode="${PRE_COMMIT_FROM_REF}..${PRE_COMMIT_TO_REF}"
  elif git rev-parse -q --verify '@{upstream}' > /dev/null 2>&1; then
    mode='@{upstream}..HEAD'
  else
    mode='origin/main..HEAD'
  fi
fi

found=0
checked=0
for var in MAIRUI_LICENCE DEEPSEEK_API_KEY; do
  val="${!var:-}"
  src="环境变量"
  if [ -z "$val" ]; then
    val="$(read_env_file "$var" || true)"
    src="env 文件"
  fi
  if ! usable "$val"; then
    unset val
    echo "notice: ${var} 在环境变量和 env 文件里都没有可用值，跳过该项比对"
    continue
  fi
  checked=$((checked + 1))
  printf '%s\n' "$val" > "$tmp"
  unset val
  hit=0
  case "$mode" in
    worktree) git grep -qF -f "$tmp" && hit=1 ;;
    cached) git grep -qF --cached -f "$tmp" && hit=1 ;;
    history | *..*)
      if [ "$mode" = history ]; then revs="$(git rev-list --all)"; else revs="$(git rev-list "$mode")"; fi
      for rev in $revs; do
        if git grep -qF -f "$tmp" "$rev" -- 2>/dev/null; then hit=1; break; fi
      done
      ;;
    *) echo "未知模式 $mode" >&2; exit 2 ;;
  esac
  if [ "$hit" = 1 ]; then
    echo "FOUND ${var}（真实值出现在仓库内容中，模式 ${mode}，值来源 ${src}）"
    found=1
  else
    echo "not-found ${var}（模式 ${mode}，值来源 ${src}）"
  fi
done
: > "$tmp"
if [ "$checked" = 0 ]; then
  echo "notice: MAIRUI_LICENCE 与 DEEPSEEK_API_KEY 都没有可用值，真实值比对已跳过"
fi
exit "$found"
