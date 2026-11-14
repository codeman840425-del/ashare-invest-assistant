#!/usr/bin/env python3
"""Synthetic-only O-03 tests. Temporary fake dumps and fake Docker; no real DB."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
HELPER = SCRIPTS / "db-backup-retention.py"
BACKUP = SCRIPTS / "db-backup.sh"


class RetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="o03-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "dumps"
        self.root.mkdir(mode=0o700)

    def seed(self, day: int, *, database: str = "synthetic", protection=None) -> Path:
        stamp = f"202001{day:02}T000000Z"
        path = self.root / f"{database}-{stamp}.dump"
        value = f"synthetic-dump-{day}".encode()
        path.write_bytes(value)
        meta = {
            "database": database,
            "dump_file": path.name,
            "created_at_utc": stamp,
            "size_bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
        if protection is not None:
            meta["protection"] = protection
        path.with_suffix(".meta.json").write_text(json.dumps(meta))
        return path

    def call(self, *extra: str, success: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [
                sys.executable,
                str(HELPER),
                "--directory",
                str(self.root),
                "--database",
                "synthetic",
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def snapshot(self) -> dict:
        return {
            x.name: x.read_bytes()
            for x in self.root.iterdir()
            if x.suffix in {".json", ".dump"} and not x.is_symlink()
        }

    def test_default_is_dry_run_and_keep_two(self) -> None:
        for day in range(1, 6):
            self.seed(day)
        before = self.snapshot()
        result = self.call()
        self.assertIn('"candidates": 3', result.stdout)
        self.assertIn('"deleted": 0', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_apply_preserves_latest_two_pairs(self) -> None:
        paths = [self.seed(day) for day in range(1, 6)]
        # An old dump with a new mtime must still be removed by UTC filename order.
        os.utime(paths[0], (2000000000, 2000000000))
        self.call("--apply")
        self.assertEqual(
            sorted(x.name for x in self.root.glob("*.dump")),
            [x.name for x in paths[-2:]],
        )
        self.assertEqual(len(list(self.root.glob("*.meta.json"))), 2)

    def test_parameterized_keep_and_protected_not_counted(self) -> None:
        held = self.seed(1, protection=True)
        for day in range(2, 5):
            self.seed(day, protection=False)
        held2 = self.seed(5, protection=True)
        before_held = held.read_bytes(), held.with_suffix(".meta.json").read_bytes()
        self.call("--keep", "1", "--apply")
        self.assertTrue(held.exists() and held2.exists())
        self.assertEqual(len(list(self.root.glob("*.dump"))), 3)
        self.assertEqual(
            (held.read_bytes(), held.with_suffix(".meta.json").read_bytes()),
            before_held,
        )
        self.assertTrue((self.root / "synthetic-20200104T000000Z.dump").exists())

    def test_unrelated_database_and_files_untouched(self) -> None:
        other = self.seed(1, database="other")
        note = self.root / "README"
        note.write_text("synthetic-note")
        for day in range(1, 5):
            self.seed(day)
        self.call("--apply")
        self.assertTrue(other.exists())
        self.assertEqual(note.read_text(), "synthetic-note")

    def test_missing_meta_refuses_entire_rotation(self) -> None:
        for day in range(1, 5):
            self.seed(day)
        (self.root / "synthetic-20200104T000000Z.meta.json").unlink()
        before = self.snapshot()
        self.call("--apply", success=False)
        self.assertEqual(before, self.snapshot())

    def test_corrupt_hash_refuses_even_protected_file(self) -> None:
        for day in range(1, 5):
            self.seed(day)
        bad = self.seed(5, protection=True)
        bad.write_bytes(b"synthetic-corruption")
        before = self.snapshot()
        self.call("--apply", success=False)
        self.assertEqual(before, self.snapshot())

    def test_invalid_json_or_protection_refuses(self) -> None:
        bad = self.seed(1, protection="false")
        before = self.snapshot()
        self.call("--apply", success=False)
        self.assertEqual(before, self.snapshot())
        bad.with_suffix(".meta.json").write_text("not-json")
        self.call("--apply", success=False)
        self.assertTrue(bad.exists())

    def test_new_backup_never_deleted_on_clock_reversal(self) -> None:
        first = self.seed(1)
        for day in range(2, 5):
            self.seed(day)
        before = self.snapshot()
        self.call("--apply", "--new-backup", first.name, success=False)
        self.assertEqual(before, self.snapshot())

    def test_symlink_directory_refused(self) -> None:
        self.seed(1)
        link = Path(self.temp.name) / "linked-directory"
        link.symlink_to(self.root, target_is_directory=True)
        result = subprocess.run(
            [
                sys.executable,
                str(HELPER),
                "--directory",
                str(link),
                "--database",
                "synthetic",
                "--apply",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(list(self.root.glob("*.dump"))), 1)

    def test_invalid_keep_refuses(self) -> None:
        self.seed(1)
        for keep in ("0", "-1", "bad", "1000000"):
            self.call("--keep", keep, "--apply", success=False)
        self.assertEqual(len(list(self.root.glob("*.dump"))), 1)

    def test_symlink_dump_and_meta_refused_without_touching_target(self) -> None:
        path = self.seed(1)
        outside = Path(self.temp.name) / "outside"
        outside.write_bytes(b"synthetic-outside")
        path.unlink()
        path.symlink_to(outside)
        self.call("--apply", success=False)
        self.assertEqual(outside.read_bytes(), b"synthetic-outside")
        path.unlink()
        path = self.seed(1)
        meta = path.with_suffix(".meta.json")
        meta.unlink()
        meta.symlink_to(outside)
        self.call("--apply", success=False)
        self.assertEqual(outside.read_bytes(), b"synthetic-outside")

    def test_hardlink_refused(self) -> None:
        path = self.seed(1)
        os.link(path, Path(self.temp.name) / "outside-hardlink")
        self.call("--apply", success=False)
        self.assertTrue(path.exists())

    def test_lock_busy_refuses(self) -> None:
        for day in range(1, 5):
            self.seed(day)
        before = self.snapshot()
        with (self.root / ".db-backup-synthetic.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.call("--apply", success=False)
        self.assertEqual(self.snapshot(), before)

    def fake_backup(
        self, *args: str, fail: bool = False
    ) -> subprocess.CompletedProcess:
        bindir = Path(self.temp.name) / "bin"
        bindir.mkdir(exist_ok=True)
        fake = bindir / "docker"
        fake.write_text("""#!/usr/bin/env python3
import os, sys
args = " ".join(sys.argv[1:])
if "pg_dump" in args:
    if os.environ.get("SYNTHETIC_FAIL") == "1":
        sys.exit(1)
    print("synthetic-pgdump")
elif "current_setting" in args:
    print("16.15 2.31.0")
elif sys.argv[1] == "inspect":
    print("synthetic-image")
elif sys.argv[1] != "info":
    sys.exit(2)
""")
        fake.chmod(0o700)
        env = {
            "PATH": str(bindir) + ":/usr/bin:/bin",
            "HOME": self.temp.name,
            "AIA_ROOT": str(SCRIPTS.parents[1]),
            "SYNTHETIC_FAIL": "1" if fail else "0",
        }
        return subprocess.run(
            [
                "bash",
                str(BACKUP),
                "--db",
                "synthetic",
                "--container",
                "synthetic-only",
                "--out-dir",
                str(self.root),
                *args,
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_backup_default_dry_run_and_protect_option(self) -> None:
        for day in range(1, 5):
            self.seed(day)
        result = self.fake_backup("--protect")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(self.root.glob("*.dump"))), 5)
        latest = Path(result.stdout.strip())
        self.assertTrue(
            json.loads(latest.with_suffix(".meta.json").read_text())["protection"]
        )
        self.assertIn('"mode": "dry-run"', result.stderr)

    def test_successful_backup_rotates_only_with_explicit_flag(self) -> None:
        for day in range(1, 5):
            self.seed(day)
        result = self.fake_backup("--rotate", "--keep", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(self.root.glob("*.dump"))), 2)
        self.assertTrue(Path(result.stdout.strip()).exists())
        self.assertIn('"mode": "apply"', result.stderr)

    def test_failed_backup_never_rotates(self) -> None:
        for day in range(1, 5):
            self.seed(day)
        before = self.snapshot()
        result = self.fake_backup("--rotate", fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_keep_rejected_before_dump(self) -> None:
        result = self.fake_backup("--keep", "0", "--rotate")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(list(self.root.glob("*.dump"))), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
