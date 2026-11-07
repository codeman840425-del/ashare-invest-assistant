"""T-A14 runtime boundary only; never executes gates or changes a lifecycle."""

from __future__ import annotations


def runnable(lifecycle: str, role: str) -> bool:
    return lifecycle in {"published", "observing"} or (
        lifecycle == "simulating" and role == "admin"
    )
