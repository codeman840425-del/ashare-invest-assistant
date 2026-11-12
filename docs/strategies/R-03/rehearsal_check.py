"""R-03：仅核对合成填充、缺证与草稿边界，不执行策略或外部服务。"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from render_report import blank_packet, merge_packet, render


def main() -> None:
    checked: list[str] = []
    source = Path(__file__).with_name("synthetic_input.json")
    patch = json.loads(source.read_text(encoding="utf-8"), parse_float=Decimal)
    packet = merge_packet(blank_packet(), patch)
    text = render(packet)
    lines = text.splitlines()

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checked.append(name)

    def row(starts: str) -> str:
        return next(line for line in lines if line.startswith(starts))

    check(
        "五窗口按 phase 排列，保留集不因输入顺序变为折1",
        [
            line.split(" | ")[0]
            for line in lines
            if any(line.startswith(f"| {name}") for name in ("评估折", "保留集"))
        ]
        == [
            "| 评估折 1 (evaluation_1)",
            "| 评估折 2 (evaluation_2)",
            "| 评估折 3 (evaluation_3)",
            "| 评估折 4 (evaluation_4)",
            "| 保留集 (holdout)",
        ],
    )
    check(
        "零腿保留n=0且均值区间不可估",
        "| 0 | 0 | 不可估（0 腿） | 不可估（0 腿） |" in row("| 评估折 2"),
    )
    check(
        "缺失窗口样本量不补0",
        "| 缺证（不可判） | 缺证（不可判） | 缺样本量（不可判） |" in row("| 评估折 4"),
    )
    check(
        "缺成本不借保留集",
        "| 缺证（不可判） | unknown（不可判） |" in row("| 评估折 3"),
    )
    check(
        "临界精度完整保留",
        "| 69.99997 | [60.00010, 79.99984] | 35.00000 |" in row("| 保留集"),
    )
    check("P1源fail保留不重算", "fail（未通过）" in row("| P1 |"))
    check(
        "P8保留观察用途和unknown",
        "不自行升级为硬门" in row("| P8 |") and "unknown（不可判）" in row("| P8 |"),
    )
    check(
        "红旗疑点不当已确认缺陷",
        "红色［疑点，暂停判定］" in row("| R0 |") and "缺陷已确认" not in row("| R0 |"),
    )
    check(
        "红旗疑点在首页摘要可见",
        any("红旗摘要：R0=红色［疑点，暂停判定］" in line for line in lines[:12]),
    )
    check(
        "逐腿缺证保留黄色且不出现绿项",
        "黄色［缺证］" in row("| R13 |") and "绿色［本次范围未发现］" not in text,
    )
    check(
        "合成标记与待复核可见",
        "SYNTHETIC：合成填充演练" in text and "独立复核：pending" in text,
    )
    check(
        "全部原判据通过也不自动放行",
        "结论槽：待 T-R66 研究判读"
        in render(
            merge_packet(
                blank_packet(),
                {
                    "source_conclusion": {"status": "pass"},
                    "criteria": {pid: {"status": "pass"} for pid in packet["criteria"]},
                    "review": {
                        "state": "completed",
                        "evidence": "SYNTHETIC-review-only",
                    },
                },
            )
        ),
    )
    empty = render(blank_packet())
    check(
        "空模板有10判据15红旗且未核不呈绿",
        sum(
            line.startswith("| P") and line.split(" | ")[0][2:] in packet["criteria"]
            for line in empty.splitlines()
        )
        == 10
        and sum(
            line.startswith(f"| R{i} |")
            for line in empty.splitlines()
            for i in range(15)
        )
        == 15
        and "绿色［本次范围未发现］" not in empty,
    )
    check(
        "checkpoint范围标签不可外推",
        "指定 checkpoint 子集；不能外推全量"
        in render(merge_packet(blank_packet(), {"mode": "checkpoint"})),
    )

    negative = {
        "无证据不得标clear": {"flags": {"R1": {"state": "clear"}}},
        "无复核报告不得标completed": {"review": {"state": "completed"}},
        "未知phase拒绝": {"windows": {"evaluation_5": {}}},
        "负样本数拒绝": {"windows": {"evaluation_1": {"n": -1}}},
        "非有限均值拒绝": {"windows": {"holdout": {"mean_bp": Decimal("NaN")}}},
        "倒置区间拒绝": {"windows": {"holdout": {"low_bp": 2, "high_bp": 1}}},
        "不完整证据哈希拒绝": {"artifacts": {"summary.json": {"sha256": "incomplete"}}},
    }
    for name, invalid in negative.items():
        try:
            render(merge_packet(blank_packet(), invalid))
        except ValueError:
            checked.append(name)
        else:
            raise AssertionError(name)
    print(
        json.dumps(
            {
                "status": "pass",
                "checks": len(checked),
                "items": checked,
                "strategy_executed": False,
                "real_r2_read": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
