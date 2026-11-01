"""风险测评问卷（契约 §7.1 ``POST /me/risk-assessment``）。

plan §9 合规 3：风险承受 1–5 级，写入画像版本。

plan、契约、研究员文档都**没有给出问卷题目与计分规则** → 不自拟题目。这里只提供问卷的数据结构
和计分框架；``ACTIVE_QUESTIONNAIRE`` 为 ``None`` 时接口对任何答案返回 ``400 VALIDATION_ERROR``
（``issue = "questionnaire not configured"``）。题目由合规/研究员给出后在此登记
（T-B15，报告 TODO）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Questionnaire:
    version: str
    #: q_id → {choice → 分值}
    questions: Mapping[str, Mapping[str, int]]
    #: 升序的总分下限：总分 ≥ thresholds[i] 即至少 i+2 级（长度 4，对应 2–5 级），否则 1 级
    thresholds: Sequence[int]

    def __post_init__(self) -> None:
        if len(self.thresholds) != 4 or list(self.thresholds) != sorted(self.thresholds):
            raise ValueError("thresholds 必须是 4 个升序整数")

    def level_of(self, total: int) -> int:
        return 1 + sum(1 for t in self.thresholds if total >= t)


ACTIVE_QUESTIONNAIRE: Questionnaire | None = None


def score(
    questionnaire: Questionnaire | None, answers: Sequence[tuple[str, str]]
) -> tuple[int | None, list[dict[str, str]]]:
    """返回 ``(level, field_issues)``；有问题时 level 为 ``None``。"""
    if questionnaire is None:
        return None, [{"field": "answers", "issue": "questionnaire not configured"}]
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    total = 0
    for i, (q_id, choice) in enumerate(answers):
        options = questionnaire.questions.get(q_id)
        if options is None:
            issues.append({"field": f"answers[{i}].q_id", "issue": "unknown question"})
            continue
        if q_id in seen:
            issues.append({"field": f"answers[{i}].q_id", "issue": "duplicate question"})
            continue
        seen.add(q_id)
        if choice not in options:
            issues.append({"field": f"answers[{i}].choice", "issue": "unknown choice"})
            continue
        total += options[choice]
    missing = sorted(set(questionnaire.questions) - seen)
    if missing and not issues:
        issues.append({"field": "answers", "issue": "missing: " + ",".join(missing)})
    if issues:
        return None, issues
    return questionnaire.level_of(total), []
