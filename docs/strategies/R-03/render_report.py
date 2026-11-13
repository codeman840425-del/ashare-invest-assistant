"""R-03：将研究员核对过的读数填入判读草稿；不计算统计量或放行结论。"""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

PHASES = {
    "evaluation_1": "评估折 1",
    "evaluation_2": "评估折 2",
    "evaluation_3": "评估折 3",
    "evaluation_4": "评估折 4",
    "holdout": "保留集",
}
STATUS = {
    None: "缺证（不可判）",
    "pass": "pass（通过）",
    "fail": "fail（未通过）",
    "unknown": "unknown（不可判）",
    "unverifiable": "unverifiable（不可判）",
    "not_executed": "not_executed（未执行）",
}
FLAG_STATUS = {
    "pending": "黄色［待核］",
    "insufficient": "黄色［缺证］",
    "clear": "绿色［本次范围未发现］",
    "hit": "红色［疑点，暂停判定］",
    "confirmed": "红色［缺陷已确认，暂停判定］",
}
CRITERIA = {
    "P1": "各评估折和保留集 n、days；方案 §8.3",
    "P2": "保留集均值/区间、同号折、robustness；方案 §8.3",
    "P3": "保留集均值与 2×平均往返成本；方案 §8.3",
    "P4": "问题了结并集分子/分母；方案 §8.3",
    "P5": "A*−R 配对差、区间、配对 n；方案 §8.3",
    "P6": "训练窗 A* 邻域；方案 §8.3",
    "P7": "两环境各自 n、days、均值和区间；方案 §8.3",
    "P8": "训练边界与敏感性观察；不自行升级为硬门，方案 §8.3",
    "P9": "运行时退市核验及四分类；方案 §8.3、T-A155、T-R66b",
    "P10": "训练窗确定的启用方向；方案 §8.3",
}
ANNEX = {
    "coverage": "覆盖与剔除（各计数须带分母）",
    "splice": "拼接/分段来源与不可验证数",
    "cost_components": "成本五项（元与 bp of N 分列）",
    "sensitivity": "敏感性（费率/成交额/最低佣金/成本差/收益差）",
    "r_control": "R 组（汇总配对/反推/逐腿证据分别写）",
    "p9_crosscheck": "P9 公告证据与运行时核验（分别写）",
    "remaining": "其余缺证、负责人和下一步",
}


def blank_packet() -> dict:
    """显式空槽；None 不会被解释为实测零值。"""
    return {
        "mode": "not_executed",
        "deepseek": None,
        "run": dict.fromkeys(
            ("run_id", "scope", "code_sha", "plan_sha", "cutoff_beijing")
        ),
        "artifacts": {
            name: {"path": None, "sha256": None}
            for name in ("summary.json", "trials.csv", "legs.csv")
        },
        "review": {"state": "pending", "evidence": None},
        "source_conclusion": {"status": None, "reason": None},
        "windows": {
            phase: dict.fromkeys(
                (
                    "candidate",
                    "direction",
                    "n",
                    "days",
                    "mean_bp",
                    "low_bp",
                    "high_bp",
                    "cost_bp",
                    "status",
                    "evidence",
                )
            )
            for phase in PHASES
        },
        "criteria": {
            pid: dict.fromkeys(("status", "observation", "evidence", "gap"))
            for pid in CRITERIA
        },
        "flags": {
            f"R{i}": {
                "state": "pending",
                "observation": None,
                "evidence": None,
                "impact": None,
                "owner": None,
            }
            for i in range(15)
        },
        "annex": dict.fromkeys(ANNEX),
    }


def merge_packet(base: dict, patch: dict) -> dict:
    """只接受已约定键；显式按 phase 绑定，不依赖列表位置。"""
    if not isinstance(patch, dict):
        raise TypeError("输入必须是对象")
    for key, value in patch.items():
        if key not in base:
            raise ValueError(f"未知输入键：{key}；先核对 schema")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise TypeError(f"{key} 必须是对象")
            merge_packet(base[key], value)
        else:
            base[key] = value
    return base


def validate(packet: dict) -> None:
    if packet["mode"] not in {"not_executed", "synthetic", "checkpoint", "formal"}:
        raise ValueError("mode 必须明确为 not_executed/synthetic/checkpoint/formal")
    if packet["review"]["state"] not in {"pending", "completed"}:
        raise ValueError("独立复核状态必须为 pending/completed")
    if packet["review"]["state"] == "completed" and not packet["review"]["evidence"]:
        raise ValueError("独立复核 completed 必须有报告证据")
    for name, artifact in packet["artifacts"].items():
        digest = artifact["sha256"]
        if digest is not None and (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError(f"{name} 的 SHA256 必须完整，缺证请保留 null")
    for label, entry in [*packet["windows"].items(), *packet["criteria"].items()]:
        if entry["status"] not in STATUS:
            raise ValueError(f"{label} 原状态不受支持，先核对 schema")
    if packet["source_conclusion"]["status"] not in STATUS:
        raise ValueError("原产物 conclusion 状态不受支持")
    for phase, window in packet["windows"].items():
        for key in ("n", "days"):
            count = window[key]
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError(f"{phase}.{key} 必须为非负整数或 null")
        for key in ("mean_bp", "low_bp", "high_bp", "cost_bp"):
            value = window[key]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float, Decimal))
                or not Decimal(str(value)).is_finite()
            ):
                raise ValueError(f"{phase}.{key} 必须为有限数值或 null")
        if (
            window["low_bp"] is not None
            and window["high_bp"] is not None
            and window["low_bp"] > window["high_bp"]
        ):
            raise ValueError(f"{phase} 区间上下限倒置")
    for fid, flag in packet["flags"].items():
        if flag["state"] not in FLAG_STATUS:
            raise ValueError(f"{fid} 红旗状态不受支持")
        if flag["state"] in {"clear", "hit", "confirmed"} and not flag["evidence"]:
            raise ValueError(f"{fid} 作已核标记前必须有证据定位")


def cell(value: object) -> str:
    if value is None:
        return "缺证（不可判）"
    # 保留输入十进制精度；不在呈现层舍入或比较判定阈值。
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def table(headers: tuple[str, ...], rows: list[list[object]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(cell(v) for v in row) + " |" for row in rows),
        "",
    ]


def render(packet: dict, input_sha: str | None = None) -> str:
    validate(packet)
    modes = {
        "not_executed": "空槽模板；尚未执行",
        "synthetic": "SYNTHETIC：合成填充演练；所有数值均为虚构",
        "checkpoint": "指定 checkpoint 子集；不能外推全量",
        "formal": "完整正式产物的呈现草稿；范围仍以冻结证据为准",
    }
    run = packet["run"]
    source = packet["source_conclusion"]
    red = [
        f"{fid}={FLAG_STATUS[flag['state']]}"
        for fid, flag in packet["flags"].items()
        if flag["state"] in {"hit", "confirmed"}
    ]
    pending = sum(
        flag["state"] in {"pending", "insufficient"}
        for flag in packet["flags"].values()
    )
    flag_summary = "；".join(red) if red else "已登记红色项 0（不表示全部已核）"
    lines = [
        "# r2 判读草稿（R-03）",
        "",
        f"> {modes[packet['mode']]}",
        "> 呈现草稿待研究判读及独立复核；本工具不生成通过或放行结论。",
        "",
        f"结论槽：待 T-R66 研究判读；原产物状态={STATUS[source['status']]}；原理由={cell(source['reason'])}。",
        "",
        f"红旗摘要：{flag_summary}；待核/缺证 {pending} 项，逐项证据见红旗表。",
        "",
        f"范围：run_id={cell(run['run_id'])}；{cell(run['scope'])}；截止北京时间={cell(run['cutoff_beijing'])}。",
        "",
        f"冻结：代码 SHA={cell(run['code_sha'])}；方案 SHA={cell(run['plan_sha'])}。",
        "",
        f"独立复核：{cell(packet['review']['state'])}；证据={cell(packet['review']['evidence'])}。",
        "",
        f"归一化输入 SHA256={cell(input_sha)}；原产物三件套分别登记如下。",
        "",
        "## 三件套证据",
        "",
    ]
    lines += table(
        ("文件", "冻结路径/范围", "SHA256"),
        [
            [name, artifact["path"], artifact["sha256"]]
            for name, artifact in packet["artifacts"].items()
        ],
    )
    lines += [
        "## 五窗口主表",
        "",
        "单位：收益与成本为 bp of N；非账户收益率或年化。",
        "",
    ]
    rows = []
    for phase, label in PHASES.items():
        window = packet["windows"][phase]
        mean, low, high = window["mean_bp"], window["low_bp"], window["high_bp"]
        interval = (
            None if low is None or high is None else f"[{cell(low)}, {cell(high)}]"
        )
        if window["n"] == 0:
            mean = interval = "不可估（0 腿）"
        elif window["n"] is None:
            mean = interval = "缺样本量（不可判）"
        rows.append(
            [
                f"{label} ({phase})",
                window["candidate"],
                window["direction"],
                window["n"],
                window["days"],
                mean,
                interval,
                window["cost_bp"],
                STATUS[window["status"]],
                window["evidence"],
            ]
        )
    lines += table(
        (
            "窗口",
            "候选",
            "方向",
            "有效腿 n",
            "交易日",
            "扣费均值",
            "95% 区间",
            "平均往返成本",
            "原状态",
            "证据定位",
        ),
        rows,
    )
    lines += [
        "各行须绑定明确 phase/trial_id；均值、区间、成本须来自同一候选与范围。窗口 n=0 时仅将均值/区间展示为不可估，原输入留存供追溯；缺成本不复制其他窗口成本。",
        "",
        "## P1–P10",
        "",
    ]
    lines += table(
        ("判据", "观察值", "要求/用途", "原状态", "证据定位", "缺口/补证负责人"),
        [
            [
                pid,
                entry["observation"],
                CRITERIA[pid],
                STATUS[entry["status"]],
                entry["evidence"],
                entry["gap"],
            ]
            for pid, entry in packet["criteria"].items()
        ],
    )
    lines += ["## 红旗 R0–R14", ""]
    lines += table(
        ("编号", "检测状态", "观察值与比较对象", "证据范围", "影响", "负责人"),
        [
            [
                fid,
                FLAG_STATUS[entry["state"]],
                entry["observation"],
                entry["evidence"],
                "暂停判定"
                if entry["state"] in {"hit", "confirmed"}
                else entry["impact"],
                entry["owner"],
            ]
            for fid, entry in packet["flags"].items()
        ],
    )
    lines += ["## 必填附表槽", ""]
    lines += table(
        ("项", "观察值/来源/缺口"),
        [[label, packet["annex"][key]] for key, label in ANNEX.items()],
    )
    lines += [
        "R 组：paired.n 与 A* 数量相等仅说明汇总计数一致；没有 control_mean_bp/control_n_ok 或等价逐腿证据时，R 均值只可标推算，分布/逐腿匹配仍缺证。",
        "",
        "P9：T-R66b 公告正文证据不自动修改在跑 termination_list 或完成运行时尾段核验；是否升级分类须引用后续正式裁定。",
        "",
        "敏感性：RV-01 勘误后的高/低佣金档双边成本 +1bp/−2bp（相应净收益 −1bp/+2bp）是固定成交额且未触最低佣金的推导；本草稿不将其填为实跑观测，不重选参数或方向。",
        "",
        f"DeepSeek：{cell(packet['deepseek'])}。",
        "",
        "申请新任务：T-R66 私聊在三件套冻结后填数、复核并交编排者统一发布。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, help="按 README 核对后填写的归一化 JSON；缺省生成空槽"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--write-blank", action="store_true", help="将空槽输入 JSON 写至 out"
    )
    args = parser.parse_args()
    if args.write_blank and args.input:
        parser.error("--write-blank 不与 --input 同用")
    if args.input and args.out.resolve() == args.input.resolve():
        parser.error("输出不能覆盖输入")
    packet, input_sha = blank_packet(), None
    if args.input:
        raw = args.input.read_bytes()
        input_sha = hashlib.sha256(raw).hexdigest()
        packet = merge_packet(
            packet, json.loads(raw.decode("utf-8-sig"), parse_float=Decimal)
        )
    if args.out.name in packet["artifacts"]:
        parser.error("输出不能使用原产物三件套文件名")
    for artifact in packet["artifacts"].values():
        if artifact["path"] and args.out.resolve() == Path(artifact["path"]).resolve():
            parser.error("输出不能覆盖已登记的三件套证据")
    content = (
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n"
        if args.write_blank
        else render(packet, input_sha)
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(content, encoding="utf-8", newline="\n")
    print(f"written: {args.out.name}; mode={packet['mode']}; no judgement generated")


if __name__ == "__main__":
    main()
