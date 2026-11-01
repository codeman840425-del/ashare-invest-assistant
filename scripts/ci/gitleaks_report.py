#!/usr/bin/env python3
"""把 gitleaks JSON 报告转成 plan §7.4A 要求的输出：`路径:行号:规则号 掩码值`（保留前 2 个字符）。

gitleaks 在 CI 中只写 JSON 报告到 $RUNNER_TEMP（不加 -v，不在日志打出命中值），再由本脚本掩码输出。
用法：gitleaks_report.py REPORT.json   有命中退出码 1。
"""

from __future__ import annotations

import json
import sys

from secret_scan import mask


def main(argv: list[str]) -> int:
    findings = json.load(open(argv[1], encoding="utf-8")) or []
    for f in findings:
        rule = f.get("RuleID", "?")
        where = f"{(f.get('Commit') or '')[:10]}:" if f.get("Commit") else ""
        value = f.get("Secret") or f.get("Match") or ""
        print(f"{where}{f.get('File')}:{f.get('StartLine')}:{rule} {mask(value)}")
        print(f"::error file={f.get('File')},line={f.get('StartLine') or 1},title=gitleaks {rule}::{rule} {mask(value)}")
    print(f"gitleaks: 命中 {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
