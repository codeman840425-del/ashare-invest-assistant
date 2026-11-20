"""Merge JUnit documents without discarding suites or testcase details."""
from __future__ import annotations

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

from junit_validation import validate_junit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("inputs", type=Path, nargs="+")
    args = parser.parse_args(argv)
    merged = ET.Element("testsuites")
    seen = set()
    errors = []
    for path in args.inputs:
        try:
            root = ET.parse(path).getroot()
            if root.tag == "testsuite":
                merged.append(root)
            elif root.tag == "testsuites":
                merged.extend(root)
            validate_junit(root, seen)
        except (OSError, ValueError, ET.ParseError) as error:
            errors.append(f"{path}: {error}")
    ET.ElementTree(merged).write(args.output, encoding="utf-8", xml_declaration=True)
    for error in errors:
        print(f"::error title=JUnit merge::{error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
