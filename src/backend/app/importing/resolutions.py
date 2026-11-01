"""导入提示的处理选项（契约 v0.2.4 #11 / §4.1“处理选项”表，T-F02 D3；T-B02x）。

- ``resolution_choices`` 按表生成，第一个是 ``default_resolution``；
  表里没有的提示码为 ``[]`` / ``None``。
- ``POST /imports/{batch_id}/findings/{finding_id}/resolve``：只要求 ``resolution_choices`` 非空，
  不看 ``needs_action``（39/40 也可以覆盖）；``choice`` 必须在表中；覆盖类选项 ``reason`` 必填
  （去掉首尾空白后 1–200 字），否则 ``400 VALIDATION_ERROR``。非覆盖类的 ``reason`` 可以不填，
  填了也不能超过 200 字。

纯函数，不读库。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from app.common.errors import AppError, ErrorCode
from app.schemas.enums import IMPORT_CODE_TABLE

REASON_MAX: Final = 200


@dataclass(frozen=True, slots=True)
class ResolutionSpec:
    choices: tuple[str, ...]
    #: 覆盖类选项：提交时必须填理由并写审计
    overrides: frozenset[str] = frozenset()

    @property
    def default(self) -> str | None:
        return self.choices[0] if self.choices else None


def _spec(*choices: str, overrides: tuple[str, ...] = ()) -> ResolutionSpec:
    return ResolutionSpec(choices=choices, overrides=frozenset(overrides))


_CONFIRM = _spec("confirm")
_DUP = _spec("keep_skipped", "force_import", overrides=("force_import",))

#: 契约 §4.1“处理选项”表（逐码）
RESOLUTION_TABLE: Final[Mapping[str, ResolutionSpec]] = MappingProxyType(
    {
        "IMPORT_ACCOUNT_MISMATCH": _spec(
            "confirm_new_holder_code", overrides=("confirm_new_holder_code",)
        ),
        "IMPORT_ENCODING_LOW_CONFIDENCE": _CONFIRM,
        "IMPORT_FORMAT_LOW_CONFIDENCE": _CONFIRM,
        "IMPORT_SNAPSHOT_AS_OF_ASSUMED": _CONFIRM,
        "IMPORT_UNKNOWN_SECURITY": _spec("import_as_is", "skip_row"),
        "IMPORT_MARKET_INFERRED_CONFLICT": _spec("use_master_data"),
        "IMPORT_UNKNOWN_BIZ_TYPE": _spec("keep_skipped", "manual_entry"),
        "IMPORT_DUPLICATE_IN_DB": _DUP,
        "IMPORT_DUPLICATE_IN_FILE": _DUP,
        "IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL": _spec(
            "skip_import_row", "keep_import_void_manual", overrides=("keep_import_void_manual",)
        ),
    }
)

_KNOWN_CODES: Final = frozenset(s.code for s in IMPORT_CODE_TABLE)
_EMPTY: Final = ResolutionSpec(choices=())

# 表里的码必须都是 §4.1 已登记的提示码（防拼写错误；导入时即失败）
_UNKNOWN = set(RESOLUTION_TABLE) - _KNOWN_CODES
if _UNKNOWN:
    raise RuntimeError(f"RESOLUTION_TABLE 含未登记的提示码：{sorted(_UNKNOWN)}")


def spec_for(code: str) -> ResolutionSpec:
    return RESOLUTION_TABLE.get(code, _EMPTY)


def resolution_choices(code: str) -> list[str]:
    """``ImportFinding.resolution_choices``。"""
    return list(spec_for(code).choices)


def default_resolution(code: str) -> str | None:
    """``ImportFinding.default_resolution``。"""
    return spec_for(code).default


def is_override(code: str, choice: str) -> bool:
    return choice in spec_for(code).overrides


def validate_resolution(code: str, choice: str, reason: str | None) -> str | None:
    """校验一次 resolve 提交，返回归一化后的理由（空白 → ``None``）。

    不合法时抛 ``400 VALIDATION_ERROR {fields: [...]}``（``choice`` / ``reason``）。
    提示码没有处理选项时，``choice`` 的 issue 为 ``not_resolvable``。
    """
    spec = spec_for(code)
    fields: list[dict[str, str]] = []
    note = (reason or "").strip() or None
    if not spec.choices:
        fields.append({"field": "choice", "issue": "not_resolvable"})
    elif choice not in spec.choices:
        fields.append({"field": "choice", "issue": "invalid"})
    if note is not None and len(note) > REASON_MAX:
        fields.append({"field": "reason", "issue": "too_long"})
    elif note is None and choice in spec.overrides:
        fields.append({"field": "reason", "issue": "required"})
    if fields:
        raise AppError(ErrorCode.VALIDATION_ERROR, details={"fields": fields})
    return note
