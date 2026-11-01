#!/usr/bin/env bash
# 真实密钥值精确比对（plan §7.4A S1/S2 “真实值精确匹配”）。
# 从环境变量读取 MAIRUI_LICENCE、DEEPSEEK_API_KEY（CI 中来自 GitHub secrets，本地来自本机环境），
# 用 git grep -qF 与仓库内容比对。任何情况下都不打印值：值只写进权限 600 的临时模式文件，
# 不出现在命令行参数里；命中只输出 FOUND 和变量名。
# 用法：check_real_secrets.sh [worktree|cached|history|RANGE]
#   worktree  已跟踪文件（工作区）      cached   暂存区（pre-commit）
#   history   全部提交（含所有分支）    A..B     区间内每个提交的完整树
# 退出码：0 未发现；1 发现；变量都未设置时输出提示并退出 0。
set -euo pipefail
mode="${1:-worktree}"
umask 077
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
found=0
checked=0
for var in MAIRUI_LICENCE DEEPSEEK_API_KEY; do
  val="${!var:-}"
  if [ -z "$val" ]; then
    echo "::notice title=secret-exact::${var} 未设置，跳过该项比对"
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
    echo "::error title=secret-exact::FOUND ${var}（真实值出现在仓库内容中，模式 ${mode}）"
    found=1
  else
    echo "not-found ${var}（模式 ${mode}）"
  fi
done
: > "$tmp"
if [ "$checked" = 0 ]; then
  echo "::notice title=secret-exact::MAIRUI_LICENCE 与 DEEPSEEK_API_KEY 都未配置，真实值比对已跳过"
fi
exit "$found"
