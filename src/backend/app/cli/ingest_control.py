"""Explicit operator-only STOP/pause writer; no action or I/O on import."""

import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--pause", action="store_true")
    action.add_argument("--resume-authorized", action="store_true")
    action.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    try:
        from app.ingest.send_control import root_from_environment
        from app.ingest.shared_gate import write_stop

        if args.stop:
            write_stop(root_from_environment() / "STOP")
        else:
            from app.config import get_settings
            from app.ingest.live import set_global_pause

            set_global_pause(get_settings(), args.pause)
        print("ingest control applied")
        return 0
    except Exception:  # noqa: BLE001 - never expose a DSN/Redis exception
        print("ingest control failed closed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
