"""``python -m app.cli <command> ...``。"""

from __future__ import annotations

import sys
from collections.abc import Callable

from app.cli.delete_user_data import main as delete_user_data_main
from app.cli.master_bootstrap import main as master_bootstrap_main

COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "delete-user-data": delete_user_data_main,
    "master-bootstrap": master_bootstrap_main,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in COMMANDS:
        print(
            "用法：python -m app.cli delete-user-data --user-id <uuid> [--execute]\n"
            "      python -m app.cli master-bootstrap [--sources a,b]",
            file=sys.stderr,
        )
        return 2
    return COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    raise SystemExit(main())
