"""``ingest:requests`` 意图解析与取数归属（plan §2.1B 第 1、4 点）。

- ``verify_licence``：只带 ``licence_id``/``verification_id``（明文不经过 Redis），
  由 :func:`app.licences.service.enqueue_verify` 投递；这里解析并校验字段。
- ``data_sharing.mode = per_licence``：取数与读取都只用**当前用户自己的证书**，
  :func:`source_licence_for` 返回要写进 ``source_licence_id`` 的证书 id；
  证书不可用时返回 ``None``（调用方给出 ``gaps[].reason = data_licence_unavailable``），
  **永不回退到别人的证书**（``allow_cross_licence_fallback`` 恒为 false）。
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.config_files import IngestDataSharing
from app.ingest.state import Priority
from app.licences.service import VERIFY_INTENT
from app.schemas.enums import DataLicenceStatus

S = DataLicenceStatus

#: 可以为用户取数的状态（过期钻石版只在状态机里放行 P0）
USABLE_STATUSES: Final = frozenset({S.ACTIVE, S.EXPIRED})
GAP_REASON: Final = "data_licence_unavailable"


class IntentError(ValueError):
    pass


@dataclass(frozen=True)
class VerifyIntent:
    licence_id: uuid.UUID
    verification_id: uuid.UUID
    priority: Priority = Priority.P0


def _s(fields: Mapping[bytes | str, bytes | str], key: str) -> str | None:
    for k in (key, key.encode()):
        if k in fields:
            v = fields[k]
            return v.decode("utf-8") if isinstance(v, bytes) else str(v)
    return None


@dataclass(frozen=True)
class VendorIntent:
    batch_id: uuid.UUID
    licence_id: uuid.UUID
    datasets: tuple[str, ...]
    deadline_at: dt.datetime
    priority: Priority = Priority.P1


def parse_vendor_intent(fields: Mapping[bytes | str, bytes | str]) -> VendorIntent:
    allowed = {"kind", "batch_id", "licence_id", "datasets", "priority", "deadline_at"}
    if {k.decode() if isinstance(k, bytes) else k for k in fields} != allowed:
        raise IntentError("vendor_lists intent: invalid fields")
    try:
        lid, bid = (
            uuid.UUID(_s(fields, "licence_id") or ""),
            uuid.UUID(_s(fields, "batch_id") or ""),
        )
        datasets = json.loads(_s(fields, "datasets") or "[]")
        deadline = dt.datetime.fromisoformat(_s(fields, "deadline_at") or "")
        required = {"hslt_list", "bj_list", "kc_list", "hsrl_real"}
        if not isinstance(datasets, list) or len(datasets) != 4 or set(datasets) != required:
            raise ValueError
        if deadline.tzinfo is None or _s(fields, "priority") != "p1_daily":
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise IntentError("vendor_lists intent: invalid metadata") from exc
    return VendorIntent(bid, lid, tuple(datasets), deadline)


def parse_intent(fields: Mapping[bytes | str, bytes | str]) -> VerifyIntent | VendorIntent | None:
    """解析一条 Stream 记录；不是 ``verify_licence`` 返回 ``None``（交给其他处理器）。

    拒绝带 ``licence`` 字段的记录（明文不得经过 Redis），错误消息不含字段值。
    """
    if _s(fields, "kind") == "vendor_lists":
        return parse_vendor_intent(fields)
    if _s(fields, "kind") != VERIFY_INTENT:
        return None
    if _s(fields, "licence") is not None:
        raise IntentError("verify_licence intent must not carry a licence value")
    try:
        lid = uuid.UUID(_s(fields, "licence_id") or "")
        vid = uuid.UUID(_s(fields, "verification_id") or "")
    except ValueError as exc:
        raise IntentError("verify_licence intent: bad licence_id/verification_id") from exc
    pr = (_s(fields, "priority") or "P0").upper()
    if pr not in {"P0", "P1", "P2"}:
        raise IntentError("verify_licence intent: bad priority")
    return VerifyIntent(lid, vid, Priority[pr])


@dataclass(frozen=True)
class UserLicence:
    user_id: uuid.UUID
    licence_id: uuid.UUID | None
    status: DataLicenceStatus


def source_licence_for(
    sharing: IngestDataSharing, user: UserLicence, priority: Priority = Priority.P1
) -> uuid.UUID | None:
    """为 ``user`` 取数/读数时使用的证书；不可用 → ``None``，绝不跨证书回退。"""
    if sharing.allow_cross_licence_fallback:  # pragma: no cover - 配置层已锁死为 false
        raise RuntimeError("allow_cross_licence_fallback must be false")
    if sharing.mode != "per_licence":  # pragma: no cover - shared_cache 待麦蕊书面确认
        raise RuntimeError(f"data_sharing.mode={sharing.mode} not enabled")
    if user.licence_id is None or user.status not in USABLE_STATUSES:
        return None
    if user.status == S.EXPIRED and priority != Priority.P0:
        return None
    return user.licence_id


def readable_by(sharing: IngestDataSharing, user: UserLicence, row_source: uuid.UUID) -> bool:
    """``per_licence``：用户只能读本人证书取到的行。"""
    if sharing.mode != "per_licence":  # pragma: no cover
        raise RuntimeError(f"data_sharing.mode={sharing.mode} not enabled")
    return user.licence_id is not None and row_source == user.licence_id
