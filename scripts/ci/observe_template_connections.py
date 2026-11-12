#!/usr/bin/env python3
"""Observe only the recorded CI template while the unchanged pytest command runs."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import psycopg
from owned_unix_resources import check_runner
from prepare_tt50_template import connect, identity
from template_connections import snapshot, template_row


def observe(conn, row: dict, sink, stop, *, once: bool = False) -> None:
    previous = None
    while not stop.is_set():
        sample = snapshot(conn, row)
        sample["schema"] = "aia-ci-template-connections-v1"
        line = json.dumps(sample, sort_keys=True)
        sink.write(line + "\n")
        sink.flush()
        signature = json.dumps({k: v for k, v in sample.items() if k != "at"}, sort_keys=True)
        if signature != previous:
            print("AIA_CI_TEMPLATE_CONNECTIONS " + line, flush=True)
            previous = signature
        if once or stop.wait(15):
            break


def main() -> int:
    try:
        env = check_runner()
        owner = identity(env)
        path = Path(os.environ["AIA_CI_TEMPLATE_RECEIPT"]).resolve()
        if not path.is_relative_to(Path(env["RUNNER_TEMP"]).resolve()):
            raise RuntimeError("Template receipt is outside this runner")
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt["owner"] != owner or receipt["state"] != "ready":
            raise RuntimeError("Wrong run or template is not ready")
        row = template_row(receipt)
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        target = path.parent / "connections.jsonl"
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as sink, connect("postgres") as conn:
            actual = str(conn.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
            if actual != owner["system_identifier"]:
                raise RuntimeError("Wrong connected CI service")
            observe(conn, row, sink, stop)
        print('AIA_CI_TEMPLATE_CONNECTIONS {"observer_stopped":true}', flush=True)
        return 0
    except (RuntimeError, OSError, ValueError, KeyError, psycopg.Error, subprocess.SubprocessError) as error:
        # Do not print error messages, inspect output, SQL text or server details.
        print(json.dumps({"template_observer_error": type(error).__name__}), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
