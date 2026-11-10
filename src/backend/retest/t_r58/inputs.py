"""Read-only input gates for the offline T-R58 runner (§2.2, §2.7)."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa

from . import data, splice
from .errors import DataFormatError

SHA256 = re.compile(r"[0-9a-f]{64}")
StockKey = tuple[str, str]


@dataclass(frozen=True)
class Lc1Input:
    path: Path
    sha256: str


@dataclass(frozen=True)
class VipdocInput:
    root: Path
    files: dict[StockKey, Lc1Input]
    manifest_sha256: str
    sums_sha256: str
    filelist_sha256: str

    def evidence(self) -> dict[str, str | int]:
        return {
            "files": len(self.files),
            "manifest_sha256": self.manifest_sha256,
            "sums_sha256": self.sums_sha256,
            "filelist_sha256": self.filelist_sha256,
        }


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise DataFormatError(f"missing or invalid evidence: {path.name}") from exc
    if not isinstance(value, dict):
        raise DataFormatError(f"evidence must be a JSON object: {path.name}")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value.lower()):
        raise DataFormatError("invalid SHA-256 in input evidence")
    return value.lower()


def verify_hf(
    root: Path, ready_path: Path, *, revision: str, expect: Mapping[str, Any], workers: int = 8
) -> dict[str, Any]:
    """Require the exact prepared HF snapshot and recheck every converted file."""
    ready = _object(ready_path)
    raw, converted = ready.get("raw"), ready.get("converted")
    if raw != {"ok": 5801, "mismatch": 0, "missing": 0} or not isinstance(converted, dict):
        raise DataFormatError("HF raw SHA gate not satisfied")
    if (
        converted.get("ok") is not True
        or converted.get("revision") != revision
        or converted.get("files") != expect["manifest_files"]
        or converted.get("semantic_samples") != 4
    ):
        raise DataFormatError("HF conversion gate not satisfied")
    for name in ("manifest", "manifest_files"):
        filename = f"{name}.{'json' if name == 'manifest' else 'csv'}"
        expected = _digest(converted.get(f"{name}_sha256"))
        if data.sha256(root / filename) != expected:
            raise DataFormatError(f"HF {filename} differs from preparation evidence")
    checked = data.check_manifest(
        root, dict(expect), verify_sha=True, workers=workers, verify_bj=False
    )
    if (
        not checked["ok"]
        or not checked["sha_verified"]
        or checked["sha_scope"] != "SH/SZ"
        or checked["manifest"].get("revision") != revision
        or any(
            checked[f"{key}_sha256"] != converted[f"{key}_sha256"]
            for key in ("manifest", "manifest_files")
        )
    ):
        raise DataFormatError("HF converted snapshot failed current manifest/SHA verification")
    return checked


def _selected_path(value: str) -> str | None:
    """Normalize only package-relative paths; never open out-of-scope inventory entries."""
    posix = value.strip().replace("\\", "/")
    pieces = posix.split("/")
    if pieces[:1] == ["."]:
        pieces.pop(0)
    if not pieces or any(p in {"", ".", ".."} or ":" in p or "\x00" in p for p in pieces):
        raise DataFormatError("unsafe path in vipdoc inventory")
    if pieces[0].lower() == "vipdoc":
        pieces.pop(0)
    if len(pieces) != 3:
        return None
    market, kind, filename = (p.lower() for p in pieces)
    if kind != "minline" or market not in ("sh", "sz"):
        return None
    name = PurePosixPath(filename)
    if name.suffix != ".lc1" or not name.stem.startswith(market):
        return None
    if not splice.selected_symbol(market.upper(), name.stem[2:]):
        return None
    return "/".join((market, kind, filename))


def _add_inventory(entries: dict[str, str], path: str, sha: str) -> None:
    key = _selected_path(path)
    if key is None:
        return
    if key in entries:
        raise DataFormatError(f"duplicate vipdoc inventory path: {key}")
    entries[key] = _digest(sha)


def _sums(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            fields = line.split(maxsplit=1)
            if len(fields) != 2:
                raise DataFormatError("invalid vipdoc SHA256SUMS row")
            digest, relative = fields
            _add_inventory(entries, relative.lstrip("*"), digest)
    return entries


def _filelist(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = csv.DictReader(file)
        if rows.fieldnames is None or not {"path", "sha256"} <= set(rows.fieldnames):
            raise DataFormatError("vipdoc filelist must supply package-relative path and sha256")
        for row in rows:
            if row["path"] is None or row["sha256"] is None:
                raise DataFormatError("incomplete vipdoc filelist row")
            _add_inventory(entries, row["path"], row["sha256"])
    return entries


def _package_evidence(root: Path, name: str) -> tuple[Path, Path, Path]:
    evidence = tuple(root / filename for filename in (name, "SHA256SUMS", "filelist.csv"))
    for path in evidence:
        if not path.is_file() or not path.resolve().is_relative_to(root) or path.is_symlink():
            raise DataFormatError(f"missing or unsafe vipdoc package evidence: {path.name}")
    return evidence[0], evidence[1], evidence[2]


def verify_vipdoc(root: Path, manifest_name: str) -> VipdocInput:
    root = root.resolve(strict=True)
    manifest, sums, filelist = _package_evidence(root, manifest_name)
    if not _object(manifest):
        raise DataFormatError("empty vipdoc package manifest")
    expected = _sums(sums)
    if not expected or expected != _filelist(filelist):
        raise DataFormatError("vipdoc SHA256SUMS and filelist disagree or are empty")
    files: dict[StockKey, Lc1Input] = {}
    vipdoc = root / "vipdoc"
    observed = splice.selected_lc1(vipdoc)
    for key, path in observed.items():
        relative = path.relative_to(vipdoc).as_posix().lower()
        digest = expected.get(relative)
        if digest is None or not path.resolve().is_relative_to(vipdoc) or path.is_symlink():
            raise DataFormatError(f"unlisted or unsafe vipdoc file: {relative}")
        if data.sha256(path) != digest:
            raise DataFormatError(f"vipdoc file SHA mismatch: {relative}")
        files[key] = Lc1Input(path, digest)
    if len(files) != len(expected):
        raise DataFormatError("vipdoc file count differs from inventories")
    return VipdocInput(root, files, data.sha256(manifest), data.sha256(sums), data.sha256(filelist))


@dataclass(frozen=True)
class LocalVipdoc:
    root: Path
    files: dict[StockKey, Lc1Input]
    inventory_sha256: str

    def evidence(self) -> dict[str, Any]:
        return {
            "mode": "one_read_only_snapshot",
            "files": len(self.files),
            "by_exchange": {ex: sum(key[0] == ex for key in self.files) for ex in ("SH", "SZ")},
            "inventory_sha256": self.inventory_sha256,
            "independent_package_equality": "not_applicable",
            "uses": {"single": "2026-08-07", "main_from": "2026-08-10"},
        }


def pin_local_vipdoc(root: Path) -> LocalVipdoc:
    """Pin exactly one read-only input; derived dates are not independent packages."""
    from hashlib import sha256

    root = root.resolve(strict=True)
    observed = splice.selected_lc1(root)
    if not observed or {key[0] for key in observed} != {"SH", "SZ"}:
        raise DataFormatError("local vipdoc must cover both SH and SZ minline")
    files = {}
    inventory = sha256()
    for key, path in sorted(observed.items()):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise DataFormatError("unsafe local vipdoc path")
        before = path.stat()
        digest = data.sha256(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise DataFormatError("local vipdoc changed while pinning snapshot")
        files[key] = Lc1Input(path, digest)
        inventory.update(f"{key[0]}/{key[1]} {digest}\n".encode("ascii"))
    return LocalVipdoc(root, files, inventory.hexdigest())


def verify_vipdoc_pair(single_root: Path, main_root: Path) -> tuple[VipdocInput, VipdocInput]:
    single_path, main_path = single_root.resolve(), main_root.resolve()
    if single_path == main_path:
        raise DataFormatError("vipdoc package roots must be distinct")
    # Reject missing inputs before hashing either package; never derive a substitute snapshot.
    _package_evidence(single_path, "tdx_min_20260807_manifest.json")
    _package_evidence(main_path, "tdx_min_manifest.json")
    single = verify_vipdoc(single_path, "tdx_min_20260807_manifest.json")
    main = verify_vipdoc(main_path, "tdx_min_manifest.json")
    for key in single.files.keys() & main.files.keys():
        if single.files[key].path.samefile(main.files[key].path):
            raise DataFormatError("vipdoc packages share a physical lc1 file")
    if {k: v.sha256 for k, v in single.files.items()} == {
        k: v.sha256 for k, v in main.files.items()
    }:
        raise DataFormatError("vipdoc packages contain identical file inventories")
    return single, main


def decode_verified(
    source: Lc1Input,
    key: StockKey,
    *,
    inventory_end: date | None = None,
) -> tuple[pa.Table, dict[str, Any]]:
    table, checks = splice.decode_lc1(source.path, *key, inventory_end=inventory_end)
    if checks["source_sha256"] != source.sha256:
        raise DataFormatError("vipdoc file changed since inventory verification")
    return table, checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify T-R58 inputs without running a strategy.")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--single-package", type=Path, required=True)
    parser.add_argument("--main-package", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    config = data.load_config(Path(__file__).with_name("config.yaml"))
    try:
        single, main_package = verify_vipdoc_pair(args.single_package, args.main_package)
        hf_dir = args.data_root / "hf-1min"
        hf = verify_hf(
            hf_dir / "2022plus",
            hf_dir / "T-B136-hf-ready.json",
            revision=config["data"]["hf_revision"],
            expect=config["expect"],
            workers=args.workers,
        )
    except (DataFormatError, OSError) as exc:
        print(json.dumps({"inputs_verified": False, "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "inputs_verified": True,
                "strategy_run": False,
                "hf_manifest_sha256": hf["manifest_sha256"],
                "vipdoc_single": single.evidence(),
                "vipdoc_main": main_package.evidence(),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
