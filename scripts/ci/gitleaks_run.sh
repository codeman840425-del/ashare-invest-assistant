#!/usr/bin/env bash
# CI 的 gitleaks 调用（secret-scan.yml 与 scripts/ci/tests 共用）。
# 用法：gitleaks_run.sh history REPORT.json        # 全部历史（--all），不排除任何路径
#       gitleaks_run.sh range A..B REPORT.json     # 区间内的提交，排除构建产物 src/frontend/**/dist/（T-O03）
# 只写 JSON 报告（不加 -v，日志里没有命中值），掩码输出与退出码由 gitleaks_report.py 负责。
# 排除范围必须与 secret_scan.py 的 BUILD_OUTPUT_RE 一致。
set -euo pipefail
GITLEAKS_BIN="${GITLEAKS_BIN:-gitleaks}"
BUILD_OUTPUT_EXCLUDE=':(exclude,glob)src/frontend/**/dist/**'
mode="${1:?mode: history|range}"
case "$mode" in
  history) report="${2:?report}"; opts="--all" ;;
  range)   range="${2:?range A..B}"; report="${3:?report}"; opts="$range -- . $BUILD_OUTPUT_EXCLUDE" ;;
  *) echo "gitleaks_run.sh: 未知模式 $mode" >&2; exit 2 ;;
esac
"$GITLEAKS_BIN" git . --no-banner -c .gitleaks.toml --ignore-gitleaks-allow \
  --log-opts="$opts" -f json -r "$report" --exit-code 0 -l warn
