"""Shared fail-closed checks for pytest JUnit artifacts."""
from __future__ import annotations

import xml.etree.ElementTree as ET
import re


def validate_junit(root: ET.Element, seen: set[tuple[str, str]] | None = None) -> list[ET.Element]:
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("expected testsuite or testsuites")
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError("JUnit has zero testcases")
    # Count descendant details, never add a nested suite's declared aggregate to
    # its children. Validate each level independently, including testsuites roots.
    for suite in root.iter():
        if suite.tag not in {"testsuite", "testsuites"}:
            continue
        details = list(suite.iter("testcase"))
        counts = {"tests": len(details)}
        for attribute, tag in (("failures", "failure"), ("errors", "error"),
                               ("skipped", "skipped"), ("disabled", "disabled")):
            counts[attribute] = sum(case.find(tag) is not None for case in details)
        for attribute, actual in counts.items():
            declared = suite.get(attribute)
            if declared is not None and (
                re.fullmatch(r"[0-9]+", declared) is None or int(declared) != actual
            ):
                raise ValueError(f"JUnit {suite.tag} {attribute}={declared!r} differs from details={actual}")
    if next(root.iter("failure"), None) is not None or next(root.iter("error"), None) is not None:
        raise ValueError("JUnit contains failure or error")
    if seen is None:
        seen = set()
    for case in cases:
        node = (case.get("classname", ""), case.get("name", ""))
        if node in seen:
            raise ValueError(f"duplicate JUnit node: {node}")
        seen.add(node)
    return cases
