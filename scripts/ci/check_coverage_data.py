"""Reject unreadable or empty shard coverage data before coverage combine."""
from __future__ import annotations

import argparse
from pathlib import Path

from coverage import CoverageData
from coverage.exceptions import CoverageException


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+")
    args = parser.parse_args(argv)
    errors = []
    for path in args.inputs:
        try:
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError("missing or empty coverage file")
            data = CoverageData(basename=str(path))
            data.read()
            files = data.measured_files()
            if not files or not any(data.lines(name) for name in files):
                raise ValueError("coverage file has no measurement data")
        except (OSError, ValueError, CoverageException) as error:
            errors.append(f"{path}: {error}")
    for error in errors:
        print(f"::error title=coverage data::{error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
