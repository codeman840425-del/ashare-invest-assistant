"""T-B136: anonymously fetch approved public TDX archives into the ignored data area."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

URLS = {
    "hsjday": "https://data.tdx.com.cn/vipdoc/hsjday.zip",
    "gbbq": "https://www.tdx.com.cn/products/data/data/dbf/gbbq.zip",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def prepare(root: Path) -> dict[str, object]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {}
    for name, url in URLS.items():
        archive = root / f"{name}.zip"
        if not archive.exists():
            temporary = root / f"{name}.zip.part"
            # Only these fixed HTTPS public URLs; no cookies, tokens or login state.
            with (
                urllib.request.urlopen(url, timeout=120) as source,  # noqa: S310
                temporary.open("xb") as target,
            ):
                shutil.copyfileobj(source, target, length=1024 * 1024)
            if not zipfile.is_zipfile(temporary):
                raise ValueError("public endpoint returned a non-ZIP response; preserve and stop")
            temporary.rename(archive)
        destination = (root / name).resolve()
        destination.mkdir(exist_ok=True)
        count = 0
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError(f"corrupt public archive: {name}")
            for member in bundle.infolist():
                relative = Path(member.filename.replace("\\", "/"))
                target = (destination / relative).resolve()
                if relative.is_absolute() or not target.is_relative_to(destination):
                    raise ValueError("archive path outside its destination")
                if member.is_dir() or member.filename.endswith(("/", "\\")):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source:
                    if target.exists():
                        expected = hashlib.sha256(source.read()).hexdigest()
                        if digest(target) != expected:
                            raise ValueError("existing extracted file differs; preserve and stop")
                    else:
                        with target.open("xb") as stream:
                            shutil.copyfileobj(source, stream, length=1024 * 1024)
                count += 1
        result[name] = {"sha256": digest(archive), "files": count}
        print(json.dumps({"stage": "tdx_extracted", "archive": name,
                          "sha256": digest(archive), "files": count}), flush=True)
    coverage: dict[str, str] = {}
    for code in ("sh000001", "sh000300"):
        path = root / "hsjday" / "sh" / "lday" / f"{code}.day"
        raw = path.read_bytes()
        if len(raw) % 32:
            raise ValueError("daily index record truncated")
        dates = [datetime.strptime(str(row[0]), "%Y%m%d").date()
                 for row in struct.iter_unpack("<IIIIIfII", raw)]
        if not dates or max(dates).isoformat() < "2026-11-10":
            raise ValueError("daily index does not cover 2026-11-10")
        coverage[code] = max(dates).isoformat()
    result["index_coverage"] = coverage
    (root / "T-B136-tdx-manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.out), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
