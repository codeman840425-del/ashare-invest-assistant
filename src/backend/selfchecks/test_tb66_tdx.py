"""T-B66：全虚构持仓的编码、版式与跨kind失败回归；不读取任何真实样本。

当前问题在kind选择/手选跨类型恢复路径，不能自动把成交导入改为持仓快照。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.importing.parsers.tdx import POSITIONS
from app.importing.preview import PreviewContext, PreviewOptions, preview_bytes
from app.importing.text import display_width

# 全部字段人为构造，不来自真实文件；真实校验程序另在本机内存运行。
FAKE_ROWS = (
    (
        "57",
        "609731",
        "虚构甲六六",
        "314159",
        "161803",
        "93.47",
        "86.53",
        "29365137.73",
        "-928.31",
        "-17.37",
        "FAKEK66AAA111",
    ),
    (
        "83",
        "609732",
        "虚构 乙六六",
        "271828",
        "141421",
        "79.61",
        "83.29",
        "23521767.84",
        "+763.19",
        "+23.49",
        "FAKEK66BBB222",
    ),
)
WIDTHS = (8, 14, 24, 14, 14, 14, 14, 20, 18, 18, 22)


def fixed_row(values: tuple[str, ...]) -> str:
    return "".join(
        value + " " * (width - display_width(value))
        for value, width in zip(values, WIDTHS, strict=True)
    ).rstrip()


def fake_text(newline: str = "\r\n") -> str:
    header = tuple(column.name for column in POSITIONS.columns)
    return newline.join(
        [
            "人民币: 余额:867530.19  可用:765432.81",
            "-" * 80,
            "",
            fixed_row(header),
            *(fixed_row(row) for row in FAKE_ROWS),
            "",
        ]
    )


def context() -> PreviewContext:
    return PreviewContext(
        account_id="tb66_fictional",
        today=dt.date(2026, 11, 7),
        uploaded_at=dt.datetime(2026, 11, 7, tzinfo=dt.UTC),
        holder_hmac=lambda value: hashlib.sha256(("fictional-only:" + value).encode()).hexdigest(),
    )


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "gbk", "gb18030"])
@pytest.mark.parametrize("newline", ["\r\n", "\n"])
@pytest.mark.parametrize("pinned", [False, True])
def test_positions_automatic_and_explicit(encoding: str, newline: str, pinned: bool) -> None:
    data = fake_text(newline).encode(encoding)
    options = PreviewOptions(
        parser_id="tdx_positions_v1" if pinned else None,
        encoding_override=encoding if pinned else None,
    )
    result = preview_bytes(data, "positions", options, context())
    assert result.status == "previewed"  # noqa: S101
    assert result.parser_id == "tdx_positions_v1"  # noqa: S101
    assert len(result.rows) == len(FAKE_ROWS)  # noqa: S101
    assert not any(row.has_error for row in result.rows)  # noqa: S101
    for parsed, fake in zip(result.rows, FAKE_ROWS, strict=True):
        assert parsed.normalized is not None  # noqa: S101
        assert parsed.normalized["security_code"] == fake[1]  # noqa: S101
        assert parsed.normalized["name"] == fake[2]  # noqa: S101
        assert parsed.normalized["qty"] == fake[3]  # noqa: S101
        assert fake[-1] not in parsed.raw_masked  # noqa: S101
        assert fake[-1] not in str(parsed.normalized)  # noqa: S101


@pytest.mark.parametrize("encoding", ["utf-8", "gbk"])
def test_wrong_import_kind_reproduces_positions_candidate(encoding: str) -> None:
    data = fake_text().encode(encoding)
    result = preview_bytes(data, "trades", PreviewOptions(), context())
    finding = next(f for f in result.file_findings if f["code"] == "IMPORT_UNRECOGNIZED_FORMAT")
    assert result.status == "failed"  # noqa: S101
    assert not result.rows  # noqa: S101
    assert finding["params"]["candidate_ids"] == ["tdx_positions_v1"]  # noqa: S101
    # 只重选正确编码不会改变上传时的文件种类；不暗中将成交转为快照。
    retry = preview_bytes(data, "trades", PreviewOptions(encoding_override=encoding), context())
    assert retry.status == "failed"  # noqa: S101
    assert not retry.rows  # noqa: S101


def test_bad_columns_remain_rejected_without_guessing() -> None:
    text = fake_text().replace(fixed_row(FAKE_ROWS[0]), " " + fixed_row(FAKE_ROWS[0]))
    result = preview_bytes(text.encode(), "positions", PreviewOptions(), context())
    assert result.rows[0].has_error  # noqa: S101
    assert not result.rows[1].has_error  # noqa: S101


def test_cross_kind_pinned_parser_does_not_change_import_kind() -> None:
    result = preview_bytes(
        fake_text().encode(),
        "trades",
        PreviewOptions(parser_id="tdx_positions_v1", encoding_override="utf-8"),
        context(),
    )
    assert result.status == "failed"  # noqa: S101
    assert not result.rows  # noqa: S101


@pytest.mark.parametrize("forced", ["utf-8", "utf-8-sig"])
def test_wrong_explicit_encoding_is_not_silently_overridden(forced: str) -> None:
    result = preview_bytes(
        fake_text().encode("gbk"),
        "positions",
        PreviewOptions(parser_id="tdx_positions_v1", encoding_override=forced),
        context(),
    )
    assert result.status == "failed"  # noqa: S101
    assert not result.rows  # noqa: S101
