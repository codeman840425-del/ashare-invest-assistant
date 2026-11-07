"""T-B58 币种/单位离线用例与更正回放（标准库，不连库/网络）。

运行：python selfchecks/tb58.py [--replay <run_dir> ...]
更正结果单独写 p13_analysis.corrected-T-B58.json，原始分析与响应均不覆盖。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probes"))
from p13_analyze import (
    SUBDIR,
    analyze,
    currency_unit_conclusion,
    currency_unit_fields,
    load_first_seen,
    load_raw,
    selftest_pure,
)


def assess(value: object) -> dict:
    return currency_unit_conclusion(currency_unit_fields({"sample": value}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", nargs="*", type=Path, default=[])
    args = parser.parse_args()
    results = []

    def check(ok: object, name: str) -> None:
        results.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name)

    for row in selftest_pure():
        # Existing probe pure selftests return (label, bool, detail).
        check(row[1], "p13: " + row[0])

    business = [
        {
            "hbzj": 100,
            "yfbzj": 22,
            "bhbfzhbqsljlr": 3,
            "qdfzgsjqtywdwzfdxjje": 4,
            "wbbzbzhc": 5,
            "ysfbzk": 7,
        }
    ]
    x = assess(business)
    check(
        not x["fields_found"] and x["status"] == "unconfirmed", "hbzj/yfbzj 等业务字段不是币种/单位"
    )
    check("只靠数量级不连续检查" in x["conclusion"], "业务字段反例输出未确认/数量级检查")
    x = assess([{"note": "USD 万元", "zczj": "1.0 万元", "company": "港币"}])
    check(not x["fields_found"] and not x["unit_mismatch"], "任意字符串/金额后缀不当作元数据")
    x = assess([{"currency": " CNY ", "amount_unit": "元"}])
    check(x["status"] == "confirmed" and not x["unit_mismatch"], "明确 CNY/元正例")
    x = assess({"metadata": {"currency_code": "USD", "monetary_unit": "元"}, "data": [{"hbzj": 1}]})
    check(x["status"] == "confirmed" and x["unit_mismatch"], "响应元数据 USD/元确认且不换算")
    x = assess([{"币种": "人民币", "金额单位": "万元"}])
    check(x["status"] == "confirmed" and x["unit_mismatch"], "人民币/万元需 unit_mismatch")
    x = assess([{"bz": "CNY", "dw": "元"}])
    check(x["status"] == "confirmed", "精确 bz/dw 加明确取值正例")
    for value in [None, "", "unknown", 100, {"unit": "元"}]:
        x = assess([{"currency": value, "unit": "元"}])
        check(x["status"] == "unconfirmed", "未知/非字符串币种不可确认: " + type(value).__name__)
    x = assess([{"currency": "CNY"}])
    check(x["status"] == "unconfirmed", "仅币种不推定单位")
    x = assess([{"currency": "CNY", "unit": "元"}, {"currency": "HKD", "unit": "元"}])
    check(
        x["status"] == "unconfirmed" and x["by_response"]["sample"]["conflict"],
        "冲突元数据不宣称统一口径",
    )
    x = currency_unit_conclusion(
        currency_unit_fields({"a": [{"currency": "CNY", "unit": "元"}], "b": business})
    )
    check(x["status"] == "unconfirmed", "单个响应确认不得外推整个批次")
    check(assess([])["status"] == "unconfirmed", "空响应不可确认")

    for run in args.replay:
        original = run / "p13_analysis.json"
        source_files = [
            *sorted((run / SUBDIR).glob("raw_*.json")),
            original,
            run / SUBDIR / "plan_meta.json",
            run / SUBDIR / "manifest.json",
        ]
        digests = {
            str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source_files
        }
        old = json.loads(original.read_text())
        corrected = analyze(
            load_raw(run),
            json.loads((run / SUBDIR / "plan_meta.json").read_text()),
            load_first_seen(run),
        )
        check(
            all(old[k] == corrected[k] for k in old if k != "9_currency_unit"),
            run.name + " 非⑨分析完全不变",
        )
        cu = corrected["9_currency_unit"]
        check(
            cu["status"] == "unconfirmed" and not cu["fields_found"],
            run.name + " 原误报更正为未确认",
        )
        output = run / "p13_analysis.corrected-T-B58.json"
        provenance = run / "p13_analysis.corrected-T-B58.provenance.json"
        # Exclusive create: never overwrite original or a previous correction.
        if output.exists() or provenance.exists():
            raise FileExistsError("更正产物已存在，不覆盖: " + str(output))
        with output.open("x") as f:
            json.dump(corrected, f, ensure_ascii=False, indent=2)
        with provenance.open("x") as f:
            json.dump(
                {
                    "task": "T-B58",
                    "original": original.name,
                    "correction": output.name,
                    "changed_section": "9_currency_unit",
                    "input_sha256": digests,
                    "method": "离线重算，不代表生产验收",
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        check(
            all(
                hashlib.sha256((run / p).read_bytes()).hexdigest() == digest
                for p, digest in digests.items()
            ),
            run.name + " 原始取证SHA256未变",
        )
        print("更正回放: " + str(output))

    print(f"{sum(results)} passed, {len(results) - sum(results)} failed")
    return int(not all(results))


if __name__ == "__main__":
    raise SystemExit(main())
