"""Explicit one-request verification authorization, separate from the daily list receipt."""

from __future__ import annotations

import datetime as dt
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

AUTHORIZATION = Path("/run/aia/authorizations/mairui-verification.json")
MAX_AGE = dt.timedelta(days=30)  # Never outlive the request log's dedup retention.


@dataclass(frozen=True)
class VerificationGrant:
    user_id: uuid.UUID
    licence_id: uuid.UUID
    receipt_id: uuid.UUID
    start: dt.datetime
    end: dt.datetime
    max_http_requests: int = 1

    def valid(self, licence_id: uuid.UUID, now: dt.datetime) -> bool:
        return (
            self.licence_id == licence_id
            and type(self.max_http_requests) is int
            and self.max_http_requests == 1
            and self.start.tzinfo is not None
            and self.end.tzinfo is not None
            and now.tzinfo is not None
            and dt.timedelta(0) < self.end - self.start <= MAX_AGE
            and self.start <= now < self.end
        )


def read_grant(path: Path = AUTHORIZATION) -> VerificationGrant | None:
    """Operator-installed root-owned 0444 receipt; no API/env flag grants a request."""
    try:
        parent = path.parent.stat()
        if (
            path.parent.resolve() != path.parent.absolute()
            or parent.st_uid != 0
            or parent.st_mode & 0o022
        ):
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except (OSError, AttributeError):
        return None
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o444
        ):
            return None
        raw = os.read(fd, 8193)
        if len(raw) > 8192:
            return None
        obj = json.loads(raw)
        if set(obj) != {
            "kind",
            "user_id",
            "licence_id",
            "receipt_id",
            "not_before",
            "expires_at",
            "max_http_requests",
        }:
            return None
        if (
            obj["kind"] != "mairui_licence_verification"
            or type(obj["max_http_requests"]) is not int
            or obj["max_http_requests"] != 1
        ):
            return None
        start, end = (
            dt.datetime.fromisoformat(obj["not_before"]),
            dt.datetime.fromisoformat(obj["expires_at"]),
        )
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or not dt.timedelta(0) < end - start <= MAX_AGE
            or not start <= dt.datetime.now(dt.UTC) < end
        ):
            return None
        return VerificationGrant(
            uuid.UUID(obj["user_id"]),
            uuid.UUID(obj["licence_id"]),
            uuid.UUID(obj["receipt_id"]),
            start,
            end,
        )
    except (ValueError, KeyError, TypeError):
        return None
    finally:
        os.close(fd)
