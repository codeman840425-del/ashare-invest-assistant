"""回放测试工具（T-T01）：FakeClock、Tape、ReplayClient。纯标准库，不联网。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# licence 疑似样式：URL 路径中 32 位以上的十六进制/字母数字串，或显式的 licence 字段。
LICENCE_LIKE = re.compile(r"""(?i)(licen[cs]e\s*["'=:]|/[0-9a-z]{24,}(?:/|$|\?|"))""")


class FakeClock:
    """可控时钟：被测代码通过注入的 now() 取时间。"""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock 需要带时区的时间")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        self._now += timedelta(seconds=seconds)
        return self._now


@dataclass(frozen=True)
class Frame:
    t: datetime
    endpoint: str
    params: dict[str, Any]
    status: int
    body: Any


@dataclass
class Tape:
    path: Path
    frames: list[Frame] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Tape":
        frames: list[Frame] = []
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            if LICENCE_LIKE.search(line):
                raise ValueError(f"{path.name}:{lineno} 疑似包含 licence")
            raw = json.loads(line)
            frames.append(
                Frame(
                    t=datetime.fromisoformat(raw["t"]),
                    endpoint=raw["endpoint"],
                    params=raw.get("params", {}),
                    status=int(raw["status"]),
                    body=raw.get("body"),
                )
            )
        if any(b.t < a.t for a, b in zip(frames, frames[1:])):
            raise ValueError(f"{path.name} 的时间戳不是单调递增")
        return cls(path=path, frames=frames)


class UnrecordedRequest(LookupError):
    pass


class ReplayClient:
    """按时钟返回"此刻之前最近一次"录制的响应；没有录制则抛 UnrecordedRequest（绝不回落到真实网络）。"""

    def __init__(self, tape: Tape, clock: FakeClock) -> None:
        self.tape = tape
        self.clock = clock
        self.calls: list[tuple[datetime, str]] = []

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Frame:
        params = params or {}
        now = self.clock.now()
        self.calls.append((now, endpoint))
        candidates = [
            f for f in self.tape.frames if f.endpoint == endpoint and f.params == params and f.t <= now
        ]
        if not candidates:
            raise UnrecordedRequest(f"{endpoint} {params} @ {now.isoformat()} 无录制")
        return candidates[-1]
