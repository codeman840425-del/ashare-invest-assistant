"""到期提醒（plan §2.1B 第 6 点：用户填写的 ``expires_on`` 前 30、7、1 天各一次，北京时间）。"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence


def reminders_due(
    expires_on: dt.date | None,
    today: dt.date,
    days: Sequence[int],
    already_sent: Iterable[int] = (),
) -> list[int]:
    """返回今天应发、且尚未发过的提醒档位（如 ``[7]``）。

    错过的档位（例如服务停机跨过了 30 天那天）只补发**最近的一个**，不连发多条；
    已过期或未填写到期日 → 空列表（过期由状态机发 ``expired`` 通知）。
    """
    if expires_on is None:
        return []
    left = (expires_on - today).days
    if left < 0:
        return []
    sent = set(already_sent)
    passed = [d for d in days if left <= d and d not in sent]
    if not passed:
        return []
    return [min(passed)]


def reminder_key(licence_id: object, expires_on: dt.date, day: int) -> str:
    """幂等键：同一证书、同一到期日、同一档位只发一次（到期日被修改则重新计）。"""
    return f"data_licence:expiry:{licence_id}:{expires_on.isoformat()}:{day}"
