"""T-O70：deploy/ 里 alpine:3.x 必须带 digest。不连网。"""

from __future__ import annotations

from pathlib import Path

import check_alpine_pin as cap
from conftest import REPO


def test_repo_deploy_alpine_refs_are_pinned() -> None:
    assert cap.check(REPO) == []


def test_unpinned_alpine_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "runbook.md").write_text(
        "docker run --rm alpine:3.21 sh\n", encoding="utf-8"
    )
    errs = cap.check(tmp_path)
    assert errs and "alpine:3.21" in errs[0] and "未钉死" in errs[0]


def test_short_or_invalid_digest_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "a.sh").write_text(
        "img=alpine:3.21@sha256:abcd\n", encoding="utf-8"
    )
    errs = cap.check(tmp_path)
    assert errs and "alpine:3.21@sha256:abcd" in errs[0]


def test_pinned_alpine_and_derivative_images_ok(tmp_path: Path) -> None:
    (tmp_path / "deploy").mkdir()
    pin = "alpine:3.21@sha256:" + ("ab" * 32)
    (tmp_path / "deploy" / "ok.yml").write_text(
        "\n".join(
            [
                f"image: {pin}",
                "image: redis:7.4.12-alpine3.21@sha256:" + ("cd" * 32),
                "FROM nginx:1.31.2-alpine3.23@sha256:" + ("ef" * 32),
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert cap.check(tmp_path) == []
