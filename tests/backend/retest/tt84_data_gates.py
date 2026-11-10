"""T-T84 read-only data gates; aggregate output only, no download/conversion/write to inputs."""
from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from retest.t_r58 import data, prepare_hf

ROOT = Path(r"F:\ashare-invest-assistant\data")
KIT = ROOT / "data-kit"
VIP = Path(r"D:\西部证券\vipdoc")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    raw = prepare_hf.verify_raw(ROOT / "hf-1min/raw", KIT / "raw_expected_sha256.txt", 8)
    print(json.dumps({"D1": raw}), flush=True)
    converted = prepare_hf.compare_manifest(KIT, ROOT / "hf-1min/raw", ROOT / "hf-1min/2022plus")
    manifest = json.loads((ROOT / "hf-1min/2022plus/manifest.json").read_text(encoding="utf-8"))
    print(json.dumps({"D2": converted, "counts": {k: manifest[k] for k in (
        "source_files", "files", "stocks_by_exchange", "delisted_stocks", "empty_files",
        "failed_files", "total_rows", "first_ts", "last_ts")}}), flush=True)
    expected = {"hsjday": "b6c2a5043a76d8f9b9752b3cca1952ed697ac7bd5eebe88cd7a96809f47cee46",
                "gbbq": "c1cbc818d748079aa79749393729dbcf378adf258a22734762d19b885ed0eeab"}
    archives = {}
    for name, sha in expected.items():
        path = ROOT / "tdx-pack" / (name + ".zip")
        assert digest(path) == sha, "D3 archive digest differs"
        with zipfile.ZipFile(path) as bundle:
            members = [m for m in bundle.infolist() if not m.is_dir() and not m.filename.endswith(("/", "\\"))]
            def check(info: zipfile.ZipInfo) -> bool:
                relative = info.filename.replace("\\", "/")
                target = ROOT / "tdx-pack" / name / relative
                assert target.resolve().is_relative_to((ROOT / "tdx-pack" / name).resolve())
                return target.is_file() and digest(target) == hashlib.sha256(bundle.read(info)).hexdigest()
            with ThreadPoolExecutor(max_workers=4) as pool:
                good = sum(pool.map(check, members))
            assert good == len(members), "D3 extracted content mismatch"
            archives[name] = {"sha256": sha, "files_verified": good}
    for symbol in ("sh000001", "sh000300"):
        bars = data._day_records(ROOT / "tdx-pack/hsjday.zip", symbol[:2], symbol[2:], required=True)
        assert max(bars).isoformat() >= "2026-11-10"
        archives[symbol] = {"last_date": max(bars).isoformat()}
    print(json.dumps({"D3": archives}), flush=True)
    prefixes = {"sh": ("600", "601", "603", "605", "688", "689"),
                "sz": ("000", "001", "002", "003", "300", "301", "302")}
    selected = []
    counts = Counter()
    for ex, allowed in prefixes.items():
        for folder, extension in (("minline", "lc1"), ("fzline", "lc5")):
            for path in (VIP / ex / folder).glob("*." + extension):
                symbol = path.stem.removeprefix(ex)
                if len(symbol) == 6 and symbol.isdigit() and symbol.startswith(allowed):
                    selected.append(path)
                    counts[ex + "/" + extension] += 1
    before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in selected}
    assert counts == {"sh/lc1": 2321, "sh/lc5": 2321, "sz/lc1": 2908, "sz/lc5": 2908}
    # Read access proof without decoding or displaying market rows; no source writes.
    for p in selected:
        with p.open("rb") as stream:
            stream.read(1)
    assert before == {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in selected}
    evidence = hashlib.sha256(json.dumps(sorted((str(p.relative_to(VIP)), *v) for p, v in before.items())).encode()).hexdigest()
    print(json.dumps({"D4": {"counts": dict(counts), "stocks_lc1": 5229,
        "all_files": len(selected), "size_mtime_unchanged": True, "inventory_sha256": evidence}}), flush=True)


if __name__ == "__main__":
    main()
