#!/usr/bin/env python3
"""Plan retention for one database; delete only with explicit --apply.

Called by db-backup.sh after a successful dump while inheriting its permanent
flock. Standalone use acquires the same lock. No Docker/DB/network operations.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path


class Refused(RuntimeError):
    pass


def regular(path: Path) -> tuple[int, int, int, int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise Refused("nonregular_or_linked_file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def read_regular(path: Path) -> bytes:
    before = regular(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if (
            os.fstat(stream.fileno()).st_dev,
            os.fstat(stream.fileno()).st_ino,
        ) != before[:2]:
            raise Refused("file_replaced")
        value = stream.read()
    if regular(path) != before:
        raise Refused("file_changed")
    return value


def digest(path: Path) -> str:
    before = regular(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    value = hashlib.sha256()
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino) != before[:2]:
            raise Refused("file_replaced")
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    if regular(path) != before:
        raise Refused("file_changed")
    return value.hexdigest()


def plan(root: Path, database: str, keep: int) -> tuple[list[Path], list[dict]]:
    pattern = re.compile(re.escape(database) + r"-(\d{8}T\d{6}Z)\.dump")
    ordinary: list[Path] = []
    records: list[dict] = []
    # Validate the entire matched set before any deletion, including held files.
    for path in sorted(root.iterdir()):
        match = pattern.fullmatch(path.name)
        if not match:
            continue
        dt.datetime.strptime(match[1], "%Y%m%dT%H%M%SZ")
        meta_path = path.with_suffix(".meta.json")
        dump_stat, meta_stat = regular(path), regular(meta_path)
        meta = json.loads(read_regular(meta_path))
        if not isinstance(meta, dict):
            raise Refused("meta_not_object")
        protection = meta.get("protection", False)  # Legacy meta: ordinary backup.
        if type(protection) is not bool:
            raise Refused("protection_not_boolean")
        if (
            meta.get("database") != database
            or meta.get("dump_file") != path.name
            or meta.get("created_at_utc") != match[1]
        ):
            raise Refused("meta_identity_mismatch")
        if (
            type(meta.get("size_bytes")) is not int
            or meta["size_bytes"] <= 0
            or meta["size_bytes"] != dump_stat[2]
            or meta.get("sha256") != digest(path)
        ):
            raise Refused("dump_integrity_mismatch")
        records.append(
            {
                "path": path,
                "meta": meta_path,
                "dump_stat": dump_stat,
                "meta_stat": meta_stat,
                "protection": protection,
            }
        )
        if not protection:
            ordinary.append(path)
    # UTC filename order; filesystem mtime is never used to rank recovery points.
    candidates = ordinary[:-keep] if len(ordinary) > keep else []
    return candidates, records


def run(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", args.database):
        raise Refused("invalid_database")
    if not 1 <= args.keep <= 999999:
        raise Refused("invalid_keep")
    root = Path(args.directory).absolute()
    if root.resolve() != root or not root.is_dir():
        raise Refused("directory_not_physical")
    lock = root / (".db-backup-" + args.database + ".lock")
    if lock.is_symlink():
        raise Refused("symlink_lock")
    owned_fd = args.lock_fd is None
    fd = (
        os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        if owned_fd
        else args.lock_fd
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (info.st_dev, info.st_ino) != regular(lock)[:2]
        ):
            raise Refused("invalid_lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        candidates, records = plan(root, args.database, args.keep)
        if args.new_backup is not None:
            current = root / args.new_backup
            if (
                Path(args.new_backup).name != args.new_backup
                or current not in [x["path"] for x in records]
                or current in candidates
            ):
                raise Refused("new_backup_would_not_be_retained")
        # Recheck every identity before the first deletion. Cooperative writers
        # use this same permanent lock from before pg_dump through retention.
        for item in records:
            if (
                regular(item["path"]) != item["dump_stat"]
                or regular(item["meta"]) != item["meta_stat"]
            ):
                raise Refused("predelete_state_changed")
        for item in records:
            if item["path"] not in candidates:
                continue
            print(("delete" if args.apply else "would_delete"), item["path"].name)
            if args.apply:
                # Dump first: an interrupted deletion leaves an orphan meta,
                # never a dump whose protection flag was lost.
                item["path"].unlink()
                item["meta"].unlink()
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "keep": args.keep,
                    "ordinary": sum(not x["protection"] for x in records),
                    "protected": sum(x["protection"] for x in records),
                    "candidates": len(candidates),
                    "deleted": len(candidates) if args.apply else 0,
                },
                sort_keys=True,
            )
        )
    finally:
        if owned_fd:
            os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--keep", type=int, default=2)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--new-backup", help="new dump basename that must remain after rotation"
    )
    parser.add_argument(
        "--lock-fd", type=int, help="inherited db-backup.sh lock descriptor"
    )
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, Refused):
        # No exception text: metadata may include private/untrusted content.
        print(
            "backup_retention_refused; backup files retained where not already removed",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
