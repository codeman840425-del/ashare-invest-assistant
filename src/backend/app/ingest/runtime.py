"""Optional IngestCore handle for the ingest worker heartbeat loop (T-B113).

Wiring sets the core once; each heartbeat round calls :func:`tick_ingest_core`
so pending IP-limit rewrites run even when the user never resets (T-A84 L-8).
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ingest.core import IngestCore

_core: IngestCore | None = None


def set_ingest_core(core: IngestCore | None) -> None:
    global _core
    _core = core


def get_ingest_core() -> IngestCore | None:
    return _core


def tick_ingest_core(now: dt.datetime | None = None) -> None:
    """Invoke ``IngestCore.tick`` when a core is wired; no-op otherwise."""
    core = _core
    if core is None:
        return
    core.tick(now if now is not None else dt.datetime.now(dt.UTC))
