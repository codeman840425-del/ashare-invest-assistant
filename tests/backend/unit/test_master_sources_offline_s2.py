"""Synthetic exchange snapshots: exercise production parsers without network or database."""

from __future__ import annotations

import datetime as dt
import io
import json
import socket
import zipfile
from xml.sax.saxutils import escape

import pytest
from app.master import sources as s

DAY = dt.date(2024, 1, 2)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def reject(*args, **kwargs):
        pytest.fail("offline snapshot test attempted a socket connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def part(doc, url="https://example.invalid/synthetic-snapshot"):
    return s.Part(url, json.dumps(doc, ensure_ascii=False).encode())


def xlsx(rows):
    """Create a minimal public-format OOXML worksheet; no external sample assets."""
    content = []
    for row in rows:
        cells = "".join(
            '<c t="inlineStr"><is><t>' + escape(str(value)) + "</t></is></c>"
            for value in row
        )
        content.append("<row>" + cells + "</row>")
    xml = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(content) + "</sheetData></worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", xml)
    return buffer.getvalue()


def sheet(rows, *, cdr=False):
    return s.Part(s.szse_url("1110", "tab3" if cdr else "tab1"), xlsx(rows))


def jsonp(doc):
    return s.Part(s.bse_page_url(0), ("callback(" + json.dumps(doc) + ");").encode())


def test_snapshot_roundtrip_preserves_order_urls_and_binary_bytes():
    parts = [s.Part("https://example.invalid/one", b"\x00\xff\n"), part({"result": []})]
    raw = s.pack_parts(parts)
    assert s.pack_parts(parts) == raw
    assert s.unpack_parts(raw) == parts
    assert s.unpack_parts(s.pack_parts([])) == []
    assert raw != s.pack_parts(list(reversed(parts)))
    assert json.loads(raw)["format"] == "aia-master-raw/1"


@pytest.mark.parametrize(
    "raw, message",
    [
        (b"not-json", "原始快照包无法解析"),
        (b"[]", "原始快照包无法解析"),
        (b'{"format":"aia-master-raw/2"}', "原始快照格式未知"),
        (b'{"format":"aia-master-raw/1"}', "原始快照包无法解析"),
        (b'{"format":"aia-master-raw/1","parts":[{}]}', "原始快照包无法解析"),
        (
            b'{"format":"aia-master-raw/1","parts":[{"url":"x","b64":"%%%"}]}',
            "原始快照包无法解析",
        ),
    ],
)
def test_malformed_snapshot_rejected(raw, message):
    with pytest.raises(s.ParseError, match=message):
        s.unpack_parts(raw)


@pytest.mark.parametrize("raw", [None, "", "-", "--", " \t"])
def test_absent_names_codes_dates(raw):
    assert s.clean_name(raw) == ""
    assert s.clean_code(raw) == ""
    assert s.parse_date(raw) is None


def test_names_and_codes_keep_display_and_comparison_semantics_separate():
    assert s.clean_name(" 合 成 \tＡ\n") == "合成Ａ"
    assert s.norm_name(" 合 成 \tＡ\n") == "合成A"
    assert s.clean_code(" 000101 ") == "000101"
    assert s.clean_code(101) == ""
    assert s.clean_code("000101x") == ""


@pytest.mark.parametrize("raw", ["20240102", "2024-01-02", "2024/1/2"])
def test_accepted_date_formats(raw):
    assert s.parse_date(raw) == DAY


@pytest.mark.parametrize("raw", ["2024-02-30", "not-a-date", "2024.01.02"])
def test_invalid_dates_reject_snapshot(raw):
    with pytest.raises(s.ParseError, match="日期格式无法识别"):
        s.parse_date(raw)


def test_sse_registered_parser_replays_packed_snapshot_with_board_and_type():
    parts = [
        part(
            {
                "result": [
                    {
                        "STOCK_TYPE": "1",
                        "A_STOCK_CODE": "600101",
                        "SEC_NAME_CN": "合 成Ａ",
                        "LIST_DATE": "20240102",
                    },
                    {
                        "STOCK_TYPE": "8",
                        "COMPANY_CODE": "689101",
                        "COMPANY_ABBR": "合成CDR",
                        "LIST_DATE": "2024/1/2",
                    },
                    {
                        "STOCK_TYPE": "8",
                        "A_STOCK_CODE": "688101",
                        "SEC_NAME_CN": "合成科创",
                    },
                    {
                        "STOCK_TYPE": "2",
                        "A_STOCK_CODE": "900101",
                        "SEC_NAME_CN": "合成B",
                    },
                    {"STOCK_TYPE": "unknown", "A_STOCK_CODE": "600102"},
                ]
            }
        )
    ]
    rows = s.SOURCES["sse_list"].parse(s.unpack_parts(s.pack_parts(parts)))
    assert rows == [
        s.ListRow("600101", "合成Ａ", DAY, "SH", "main", "stock"),
        s.ListRow("689101", "合成CDR", DAY, "SH", "star", "cdr"),
        s.ListRow("688101", "合成科创", None, "SH", "star", "stock"),
    ]


def test_sse_delist_skips_b_only_and_uses_name_fallback():
    rows = s.parse_sse_delist(
        [
            part(
                {
                    "result": [
                        {
                            "A_STOCK_CODE": "600101",
                            "SEC_NAME_CN": "合 成",
                            "LIST_DATE": "20240102",
                            "DELIST_DATE": "2024-02-01",
                        },
                        {
                            "A_STOCK_CODE": "600102",
                            "COMPANY_ABBR": "优先名",
                            "SEC_NAME_CN": "备选名",
                        },
                        {"B_STOCK_CODE": "900101", "COMPANY_ABBR": "合成B"},
                    ]
                }
            )
        ]
    )
    assert rows == [
        s.DelistRow("600101", "合成", DAY, dt.date(2024, 2, 1), "SH"),
        s.DelistRow("600102", "优先名", None, None, "SH"),
    ]


@pytest.mark.parametrize(
    "body", [b"not-json", b"{}", b"null", b'{"result":{}}', b'{"result":[1]}']
)
def test_sse_malformed_result_rejected(body):
    with pytest.raises(s.ParseError):
        s.parse_sse_list([s.Part(s.SSE_QUERY, body)])


def test_szse_normal_list_real_xlsx_bytes_and_short_rows():
    rows = s.parse_szse_list(
        [
            sheet(
                [
                    [" 板块 ", " A股代码 ", "A股简称", "A股上市日期"],
                    ["主板", "000101", "合 成Ａ", "20240102"],
                    ["创业板", "300101", "合成创业", "2024/1/2"],
                    ["主板", "", "仅合成B", "20240102"],
                    ["其他板块", "000102"],
                ]
            )
        ]
    )
    assert rows == [
        s.ListRow("000101", "合成Ａ", DAY, "SZ", "main", "stock"),
        s.ListRow("300101", "合成创业", DAY, "SZ", "chinext", "stock"),
        s.ListRow("000102", "", None, "SZ", None, "stock"),
    ]


def test_szse_cdr_header_suffixes_optional_date_and_first_matching_column():
    rows = s.parse_szse_list(
        [
            sheet(
                [
                    [
                        "存托凭证代码",
                        "备用代码",
                        "存托凭证简称",
                        "首次上市日期",
                        "板块",
                    ],
                    ["001101", "001102", "合成CDR", "2024-01-02", "创业板"],
                ],
                cdr=True,
            ),
            sheet([["证券代码", "证券简称"], ["001103", "合 成"]], cdr=True),
        ]
    )
    assert rows == [
        s.ListRow("001101", "合成CDR", DAY, "SZ", "chinext", "cdr"),
        s.ListRow("001103", "合成", None, "SZ", None, "cdr"),
    ]


@pytest.mark.parametrize("cdr", [True, False])
def test_empty_xlsx_list_has_no_rows(cdr):
    assert s.parse_szse_list([sheet([], cdr=cdr)]) == []


@pytest.mark.parametrize(
    "rows,cdr,message",
    [
        ([["wrong"], ["value"]], False, "表头缺少必要列"),
        ([["证券代码"], ["001101"]], True, "CDR 表头缺少代码 / 简称列"),
        ([["证券简称"], ["合成"]], True, "CDR 表头缺少代码 / 简称列"),
    ],
)
def test_szse_missing_headers_reject(rows, cdr, message):
    with pytest.raises(s.ParseError, match=message):
        s.parse_szse_list([sheet(rows, cdr=cdr)])


def test_szse_invalid_xlsx_converts_reader_error():
    with pytest.raises(s.ParseError, match="xlsx 无法解析"):
        s.parse_szse_list([s.Part(s.szse_url("1110", "tab1"), b"not-a-zip")])


def test_szse_delist_and_rename_replay_real_synthetic_worksheets():
    assert s.parse_szse_delist(
        [
            sheet(
                [
                    ["证券代码", "证券简称", "上市日期", "终止上市日期"],
                    ["000101", "合 成", "20240102", "2024/2/1"],
                    ["200101", "合成B", "20240102", "2024/2/1"],
                    ["201101", "合成B2", "20240102", "2024/2/1"],
                ]
            )
        ]
    ) == [s.DelistRow("000101", "合成", DAY, dt.date(2024, 2, 1), "SZ")]
    assert s.parse_szse_rename(
        [
            sheet(
                [
                    ["变更日期", "证券代码", "变更前简称", "变更后简称"],
                    ["20240102", "000101", "旧 合成", "新 合成"],
                ]
            )
        ]
    ) == [s.RenameRow(DAY, "000101", "旧合成", "新合成")]


def test_bse_multiple_pages_fallback_dates_and_snapshot_replay():
    parts = [
        jsonp(
            [
                {
                    "content": [
                        {"xxzqdm": "830101", "xxzqjc": "合 成Ａ", "fxssrq": "20240102"}
                    ],
                    "totalPages": 2,
                }
            ]
        ),
        jsonp(
            [
                {
                    "content": [
                        {
                            "xxzqdm": "830102",
                            "xxzqjc": "合成B",
                            "fxssrq": "-",
                            "xxgprq": "2024/1/2",
                        }
                    ]
                }
            ]
        ),
    ]
    assert s.bse_total_pages(parts[0].body) == 2
    assert s.parse_bse_list(s.unpack_parts(s.pack_parts(parts))) == [
        s.ListRow("830101", "合成Ａ", DAY, "BJ", "bse", "stock"),
        s.ListRow("830102", "合成B", DAY, "BJ", "bse", "stock"),
    ]


@pytest.mark.parametrize("value,expected", [(0, 1), (-5, 1), ("3", 3), (101, 100)])
def test_bse_page_count_bounds(value, expected):
    assert (
        s.bse_total_pages(jsonp([{"content": [], "totalPages": value}]).body)
        == expected
    )


def test_bse_page_count_defaults_to_one():
    assert s.bse_total_pages(jsonp([{"content": []}]).body) == 1


@pytest.mark.parametrize("value", [None, "bad", {}])
def test_bse_invalid_page_count_rejected(value):
    with pytest.raises(s.ParseError, match="totalPages 无法识别"):
        s.bse_total_pages(jsonp([{"content": [], "totalPages": value}]).body)


@pytest.mark.parametrize(
    "body",
    [
        b"not-jsonp",
        b"callback([])",
        b"callback(null)",
        b"callback([null])",
        b"callback([{}])",
        b'callback([{"content":{}}])',
        b"callback(bad)",
    ],
)
def test_bse_malformed_page_rejected(body):
    with pytest.raises(s.ParseError):
        s.parse_bse_list([s.Part(s.BSE_LIST_URL, body)])


@pytest.mark.parametrize("body", [b"\xff", b'callback([{"content":[null]}])'])
def test_bse_bad_encoding_and_row_shape_have_public_error(body):
    with pytest.raises(s.ParseError, match="北交所行格式不对"):
        s.parse_bse_list([s.Part(s.BSE_LIST_URL, body)])


def test_bse_html_code_map_skips_preface_and_short_rows_and_decodes_entities():
    body = """<p>合成公开格式</p><table>
    <tr><td>表头前行</td></tr>
    <tr><th>证券 简称</th><th>上市日期</th><th>旧代码</th><th>新代码</th></tr>
    <tr><td><span>合 成</span>&amp;Ａ</td><td>2024/1/2</td><td>830101</td><td>920101</td></tr>
    <tr><td>短行</td></tr><tr></tr>
    </table>""".encode()
    assert s.parse_bse_code_map([s.Part(s.BSE_CODE_MAP_URL, body)]) == [
        s.CodeMapRow("合成&Ａ", DAY, "830101", "920101")
    ]


@pytest.mark.parametrize(
    "body,message",
    [
        (b"\xff", "编码不对"),
        (b"<table><tr><td>wrong</td></tr></table>", "没有找到表头"),
    ],
)
def test_bse_bad_code_map_rejected(body, message):
    with pytest.raises(s.ParseError, match=message):
        s.parse_bse_code_map([s.Part(s.BSE_CODE_MAP_URL, body)])


def test_source_registration_and_request_builders_are_consistent():
    assert set(s.SOURCES) == {
        "sse_list",
        "sse_delist",
        "szse_list",
        "szse_delist",
        "szse_rename",
        "bse_list",
        "bse_code_map",
    }
    assert set(s.DAILY_SOURCES) == set(s.SOURCES) - {"bse_code_map"}
    assert s.SOURCES["sse_list"].exchange == "SH"
    assert s.SOURCES["szse_rename"].kind == "rename"
    assert "STOCK_TYPE=8" in s.sse_list_url("8")
    assert "COMPANY_STATUS=3" in s.sse_delist_url()
    assert s.szse_url("1110", "tab3").endswith("CATALOGID=1110&TABKEY=tab3")
    assert s.bse_page_url(2).endswith("#page=2")
    assert s.bse_list_form(2) == {
        "page": "2",
        "typejb": "T",
        "xxfcbj[]": "2",
        "sortfield": "xxzqdm",
        "sorttype": "asc",
    }
