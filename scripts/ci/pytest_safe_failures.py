"""Flush failure identities and source locations before a CI job can time out.

Never serialize exception messages, arguments, locals, environment or captured IO.
The observer cannot change collection, reports, assertions or pytest exit codes.
"""
from __future__ import annotations

import ast
import copy
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "AIA_PYTEST_FAILURE "
_REPORTER = None
_LOG = None


def _emit(payload: dict) -> None:
    line = PREFIX + json.dumps(payload, ensure_ascii=True, sort_keys=True)
    try:
        if _REPORTER is not None:
            _REPORTER.write_line("\n" + line)
            _REPORTER.flush()
        else:
            sys.__stderr__.write(line + "\n")
            sys.__stderr__.flush()
    except Exception:
        pass  # Observability must never change a test outcome.
    if _LOG is not None:
        try:
            _LOG.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
            _LOG.flush()
        except Exception:
            pass


def _type_name(cls: type) -> str:
    value = cls.__module__ + "." + cls.__qualname__
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,199}", value) else "<type>"


def _location(filename: str, lineno: int) -> dict:
    path = Path(filename).resolve()
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        relative = "[external]"
    if not relative.startswith(("src/", "tests/", "scripts/")):
        relative = "[external]"
    return {"path": relative, "line": lineno}


class _HideConstants(ast.NodeTransformer):
    def visit_Constant(self, node):
        return ast.copy_location(ast.Constant(value="<literal>"), node)


@lru_cache(maxsize=128)
def _assertions(relative: str) -> tuple:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or path.suffix != ".py":
        return ()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return tuple(n for n in ast.walk(tree) if isinstance(n, ast.Assert))


def _assertion(location: dict) -> str | None:
    if location["path"] == "[external]":
        return None
    try:
        for node in _assertions(location["path"]):
            if node.lineno <= location["line"] <= node.end_lineno:
                safe = _HideConstants().visit(copy.deepcopy(node.test))
                return ast.unparse(safe)[:500]
    except Exception:
        pass
    return None


def _payload(item, call) -> dict:
    nodeid, separator, parameters = item.nodeid.partition("[")
    # Parameter IDs can contain arbitrary runtime values; retain only a digest.
    nodeid = re.sub(r"[^A-Za-z0-9_./:\\-]", "?", nodeid)[:400]
    error = call.excinfo.value
    chain = []
    seen = set()
    current = error
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        row = {"type": _type_name(type(current))}
        state = getattr(current, "sqlstate", None)
        if isinstance(state, str) and re.fullmatch(r"[0-9A-Z]{5}", state):
            row["sqlstate"] = state
        chain.append(row)
        current = current.__cause__ or current.__context__
    locations = []
    tb = error.__traceback__
    while tb is not None:
        locations.append(_location(tb.tb_frame.f_code.co_filename, tb.tb_lineno))
        tb = tb.tb_next
    payload = {"schema": "aia-ci-pytest-failure-v1", "nodeid": nodeid,
               "phase": call.when, "exception_chain": chain, "locations": locations[-32:]}
    if separator:
        payload["parameter_id_sha256"] = hashlib.sha256(parameters.encode()).hexdigest()[:16]
    if locations:
        payload["assertion"] = _assertion(locations[-1])
    return payload


def pytest_sessionstart(session) -> None:
    global _REPORTER, _LOG
    _REPORTER = session.config.pluginmanager.getplugin("terminalreporter")
    target = os.environ.get("AIA_CI_FAILURE_TRACE")
    if not target:
        return
    try:
        path = Path(target).resolve()
        if not path.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve()):
            raise ValueError("Trace target outside runner temporary root")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        _LOG = os.fdopen(fd, "w", encoding="utf-8")
    except Exception as error:
        _emit({"schema": "aia-ci-pytest-failure-v1", "observer_error": _type_name(type(error))})


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed and call.excinfo is not None:
        try:
            _emit(_payload(item, call))
        except Exception as error:
            _emit({"schema": "aia-ci-pytest-failure-v1", "observer_error": _type_name(type(error))})


def pytest_sessionfinish(session, exitstatus) -> None:
    global _LOG
    if _LOG is not None:
        try:
            _LOG.close()
        except Exception:
            pass
        _LOG = None
