"""交易所公开列表：抓取与解析（plan 4.6.1 / T007 §1，T-B52）。

- 每个来源的一次抓取可能有多个响应（北交所分页、深交所多个 tab、上交所多个 STOCK_TYPE），
  统一打包成一个 *原始快照*（:func:`pack_parts`，JSON：每段 url 与 base64 正文），对整个包算
  sha256；解析只读这个包，所以重放原始文件就能复现解析结果。
- 不使用任何证书；不经过 ``ingest``；**不调用麦蕊**。
- 只解析 A 股（含 CDR）；B 股行跳过。
- 解析失败抛 :class:`ParseError`（整份拒收，``reject_reason='parse_error'``）。
"""

from __future__ import annotations

import base64
import datetime as dt
import html.parser
import json
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.master.xlsx import XlsxError, read_rows

Exchange = Literal["SH", "SZ", "BJ"]


class ParseError(ValueError):
    """原始快照无法解析（只含类别描述，不含正文）。"""


class FetchError(RuntimeError):
    """抓取失败（网络、HTTP 状态、反爬跳转）。消息不含响应正文。"""


@dataclass(frozen=True, slots=True)
class Part:
    url: str
    body: bytes


@dataclass(frozen=True, slots=True)
class ListRow:
    """当前上市名单的一行。"""

    code: str
    name: str
    list_date: dt.date | None
    exchange: Exchange
    board: str | None
    type: str  # stock / cdr


@dataclass(frozen=True, slots=True)
class DelistRow:
    """终止上市名单的一行（``delist_date`` 必须有值）。"""

    code: str
    name: str
    list_date: dt.date | None
    delist_date: dt.date | None
    exchange: Exchange


@dataclass(frozen=True, slots=True)
class RenameRow:
    """深交所简称变更（SSGSGMXX tab2）。"""

    changed_on: dt.date | None
    code: str
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class CodeMapRow:
    """北交所新旧代码对照。"""

    name: str
    list_date: dt.date | None
    old_code: str
    new_code: str


Row = ListRow | DelistRow | RenameRow | CodeMapRow

# ---------------------------------------------------------------------------
# 原始快照打包
# ---------------------------------------------------------------------------


def pack_parts(parts: Sequence[Part]) -> bytes:
    """多段响应 → 一个确定性的原始快照（同样的响应得到同样的 sha256）。"""
    doc = {
        "format": "aia-master-raw/1",
        "parts": [{"url": p.url, "b64": base64.b64encode(p.body).decode("ascii")} for p in parts],
    }
    return json.dumps(doc, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def unpack_parts(raw: bytes) -> list[Part]:
    try:
        doc = json.loads(raw)
        if doc.get("format") != "aia-master-raw/1":
            raise ParseError("原始快照格式未知")
        return [
            Part(str(p["url"]), base64.b64decode(p["b64"], validate=True)) for p in doc["parts"]
        ]
    except ParseError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ParseError("原始快照包无法解析") from exc


# ---------------------------------------------------------------------------
# 规范化
# ---------------------------------------------------------------------------

_CODE = re.compile(r"^\d{6}$")
_WS = re.compile(r"\s+")


def clean_name(raw: object) -> str:
    """交易所简称原文去掉所有空白（深交所"万  科Ａ"）；全角字符保留原样。"""
    s = "" if raw is None else str(raw)
    s = _WS.sub("", s)
    return "" if s in {"-", "--"} else s


def norm_name(name: str) -> str:
    """比较用：NFKC（全角转半角）+ 去空白 + 大写。"""
    return _WS.sub("", unicodedata.normalize("NFKC", name)).upper()


def clean_code(raw: object) -> str:
    s = "" if raw is None else str(raw).strip()
    return s if _CODE.match(s) else ""


def parse_date(raw: object) -> dt.date | None:
    """``20201223`` / ``2020-12-23`` / ``2020/12/3``；``-``、空 → None；格式错 → ParseError。"""
    s = "" if raw is None else str(raw).strip()
    if s in {"", "-", "--"}:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ParseError("日期格式无法识别")


def _header_key(s: str) -> str:
    return _WS.sub("", s)


# ---------------------------------------------------------------------------
# 上交所（commonQuery JSON）
# ---------------------------------------------------------------------------

SSE_QUERY: Final = "https://query.sse.com.cn/sseQuery/commonQuery.do"
SSE_REFERER: Final = "https://www.sse.com.cn/assortment/stock/list/share/"
_SSE_SQL: Final = "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L"
#: STOCK_TYPE → board（1 主板 A 股、8 科创板；2 是 B 股，不入库）
SSE_BOARDS: Final = {"1": "main", "8": "star"}


def sse_list_url(stock_type: str) -> str:
    return (
        f"{SSE_QUERY}?sqlId={_SSE_SQL}&STOCK_TYPE={stock_type}&COMPANY_STATUS=2,4,5,7,8"
        "&type=inParams&isPagination=true&pageHelp.pageSize=10000&pageHelp.pageNo=1"
        "&pageHelp.beginPage=1&pageHelp.endPage=1&pageHelp.cacheSize=1"
    )


def sse_delist_url() -> str:
    return (
        f"{SSE_QUERY}?sqlId={_SSE_SQL}&STOCK_TYPE=1,2,8&COMPANY_STATUS=3"
        "&type=inParams&isPagination=true&pageHelp.pageSize=10000&pageHelp.pageNo=1"
        "&pageHelp.beginPage=1&pageHelp.endPage=1&pageHelp.cacheSize=1"
    )


def _sse_result(body: bytes) -> list[dict[str, Any]]:
    try:
        doc = json.loads(body)
        rows = doc["result"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ParseError("上交所响应不是预期 JSON") from exc
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ParseError("上交所 result 不是对象数组")
    return rows


#: 上交所科创板 CDR 代码段（689xxx）。交易所列表没有单独的 CDR 标记（T007 补充：
#: 689009 的 STOCK_TYPE=8、LIST_BOARD=2 与普通科创板股票相同），按上交所代码分配规则判定，
#: 待架构师确认（T-R12f：CDR 以 securities.type=cdr 识别）。
SSE_CDR_PREFIX: Final = "689"


def parse_sse_list(parts: Sequence[Part]) -> list[ListRow]:
    out: list[ListRow] = []
    for part in parts:
        for r in _sse_result(part.body):
            board = SSE_BOARDS.get(str(r.get("STOCK_TYPE", "")).strip())
            if board is None:
                continue  # B 股等
            code = clean_code(r.get("A_STOCK_CODE")) or clean_code(r.get("COMPANY_CODE"))
            name = clean_name(r.get("SEC_NAME_CN")) or clean_name(r.get("COMPANY_ABBR"))
            typ = "cdr" if board == "star" and code.startswith(SSE_CDR_PREFIX) else "stock"
            out.append(ListRow(code, name, parse_date(r.get("LIST_DATE")), "SH", board, typ))
    return out


def parse_sse_delist(parts: Sequence[Part]) -> list[DelistRow]:
    out: list[DelistRow] = []
    for part in parts:
        for r in _sse_result(part.body):
            code = clean_code(r.get("A_STOCK_CODE"))
            if not code:
                continue  # 只有 B 股代码的行
            name = clean_name(r.get("COMPANY_ABBR")) or clean_name(r.get("SEC_NAME_CN"))
            out.append(
                DelistRow(
                    code,
                    name,
                    parse_date(r.get("LIST_DATE")),
                    parse_date(r.get("DELIST_DATE")),
                    "SH",
                )
            )
    return out


# ---------------------------------------------------------------------------
# 深交所（ShowReport xlsx）
# ---------------------------------------------------------------------------

SZSE_REPORT: Final = "https://www.szse.cn/api/report/ShowReport"


def szse_url(catalog: str, tab: str) -> str:
    return f"{SZSE_REPORT}?SHOWTYPE=xlsx&CATALOGID={catalog}&TABKEY={tab}"


#: 1110：tab1 A 股、tab3 CDR（tab2 B 股、tab4 AB 股不入库）
SZSE_LIST_TABS: Final = ("tab1", "tab3")
SZSE_BOARDS: Final = {"主板": "main", "创业板": "chinext"}


def _table(body: bytes, required: Sequence[str]) -> tuple[dict[str, int], list[list[str]]]:
    try:
        rows = read_rows(body)
    except XlsxError as exc:
        raise ParseError("深交所 xlsx 无法解析") from exc
    if not rows:
        return {}, []
    header = {_header_key(h): i for i, h in enumerate(rows[0])}
    if any(_header_key(k) not in header for k in required):
        raise ParseError("深交所 xlsx 表头缺少必要列")
    return header, rows[1:]


def _cell(row: list[str], header: dict[str, int], key: str) -> str:
    i = header.get(_header_key(key))
    return row[i] if i is not None and i < len(row) else ""


def parse_szse_list(parts: Sequence[Part]) -> list[ListRow]:
    out: list[ListRow] = []
    for part in parts:
        is_cdr = "TABKEY=tab3" in part.url
        if is_cdr:
            # CDR 表的列名未实测：取"代码""简称""上市日期"三类列中第一个存在的
            header, rows = _table(part.body, ())
            code_k = next((k for k in header if k.endswith("代码")), None)
            name_k = next((k for k in header if k.endswith("简称")), None)
            date_k = next((k for k in header if k.endswith("上市日期")), None)
            if rows and (code_k is None or name_k is None):
                raise ParseError("深交所 CDR 表头缺少代码 / 简称列")
            for r in rows:
                code = clean_code(_cell(r, header, code_k or ""))
                name = clean_name(_cell(r, header, name_k or ""))
                ld = parse_date(_cell(r, header, date_k)) if date_k else None
                board = SZSE_BOARDS.get(clean_name(_cell(r, header, "板块")))
                out.append(ListRow(code, name, ld, "SZ", board, "cdr"))
            continue
        header, rows = _table(part.body, ("板块", "A股代码", "A股简称", "A股上市日期"))
        for r in rows:
            code_raw = _cell(r, header, "A股代码").strip()
            if not code_raw:
                continue  # 只发 B 股的公司
            board = SZSE_BOARDS.get(clean_name(_cell(r, header, "板块")))
            out.append(
                ListRow(
                    clean_code(code_raw),
                    clean_name(_cell(r, header, "A股简称")),
                    parse_date(_cell(r, header, "A股上市日期")),
                    "SZ",
                    board,
                    "stock",
                )
            )
    return out


def parse_szse_delist(parts: Sequence[Part]) -> list[DelistRow]:
    out: list[DelistRow] = []
    for part in parts:
        header, rows = _table(part.body, ("证券代码", "证券简称", "上市日期", "终止上市日期"))
        for r in rows:
            code = clean_code(_cell(r, header, "证券代码"))
            if code[:3] in {"200", "201"}:
                continue  # B 股
            out.append(
                DelistRow(
                    code,
                    clean_name(_cell(r, header, "证券简称")),
                    parse_date(_cell(r, header, "上市日期")),
                    parse_date(_cell(r, header, "终止上市日期")),
                    "SZ",
                )
            )
    return out


def parse_szse_rename(parts: Sequence[Part]) -> list[RenameRow]:
    out: list[RenameRow] = []
    for part in parts:
        header, rows = _table(part.body, ("变更日期", "证券代码", "变更前简称", "变更后简称"))
        for r in rows:
            out.append(
                RenameRow(
                    parse_date(_cell(r, header, "变更日期")),
                    clean_code(_cell(r, header, "证券代码")),
                    clean_name(_cell(r, header, "变更前简称")),
                    clean_name(_cell(r, header, "变更后简称")),
                )
            )
    return out


# ---------------------------------------------------------------------------
# 北交所（nqxxCnzq JSONP；代码对照 HTML）
# ---------------------------------------------------------------------------

BSE_LIST_URL: Final = "https://www.bse.cn/nqxxController/nqxxCnzq.do"
BSE_CODE_MAP_URL: Final = "https://www.bse.cn/service/code_mapping.html"
BSE_MAX_PAGES: Final = 100


def bse_list_form(page: int) -> dict[str, str]:
    return {
        "page": str(page),
        "typejb": "T",
        "xxfcbj[]": "2",
        "sortfield": "xxzqdm",
        "sorttype": "asc",
    }


def bse_page_url(page: int) -> str:
    """记录用的 URL（POST 表单的页码写进 fragment，便于区分各段）。"""
    return f"{BSE_LIST_URL}#page={page}"


def _bse_page(body: bytes) -> dict[str, Any]:
    s = body.decode("utf-8", errors="strict").strip()
    i, j = s.find("("), s.rfind(")")
    if i < 0 or j < i:
        raise ParseError("北交所响应不是 JSONP")
    try:
        doc = json.loads(s[i + 1 : j])
        page = doc[0]
        if not isinstance(page.get("content"), list):
            raise ParseError("北交所 content 不是数组")
    except ParseError:
        raise
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ParseError("北交所 JSONP 内容无法解析") from exc
    return page  # type: ignore[no-any-return]


def bse_total_pages(body: bytes) -> int:
    page = _bse_page(body)
    try:
        n = int(page.get("totalPages", 1))
    except (TypeError, ValueError) as exc:
        raise ParseError("北交所 totalPages 无法识别") from exc
    return max(1, min(n, BSE_MAX_PAGES))


def parse_bse_list(parts: Sequence[Part]) -> list[ListRow]:
    out: list[ListRow] = []
    try:
        for part in parts:
            for r in _bse_page(part.body)["content"]:
                out.append(
                    ListRow(
                        clean_code(r.get("xxzqdm")),
                        clean_name(r.get("xxzqjc")),
                        parse_date(r.get("fxssrq")) or parse_date(r.get("xxgprq")),
                        "BJ",
                        "bse",
                        "stock",
                    )
                )
    except (AttributeError, UnicodeDecodeError) as exc:
        raise ParseError("北交所行格式不对") from exc
    return out


class _TableParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_bse_code_map(parts: Sequence[Part]) -> list[CodeMapRow]:
    out: list[CodeMapRow] = []
    for part in parts:
        p = _TableParser()
        try:
            p.feed(part.body.decode("utf-8"))
            p.close()
        except UnicodeDecodeError as exc:
            raise ParseError("北交所代码对照页编码不对") from exc
        idx: dict[str, int] | None = None
        for row in p.rows:
            keys = [_header_key(c) for c in row]
            if {"证券简称", "上市日期", "旧代码", "新代码"} <= set(keys):
                idx = {k: i for i, k in enumerate(keys)}
                continue
            if idx is None or len(row) < len(idx):
                continue
            out.append(
                CodeMapRow(
                    clean_name(row[idx["证券简称"]]),
                    parse_date(row[idx["上市日期"]]),
                    clean_code(row[idx["旧代码"]]),
                    clean_code(row[idx["新代码"]]),
                )
            )
        if idx is None:
            raise ParseError("北交所代码对照页没有找到表头")
    return out


# ---------------------------------------------------------------------------
# 来源登记 + 默认抓取（httpx，串行、单连接）
# ---------------------------------------------------------------------------

Kind = Literal["list", "delist", "rename", "code_map"]


@dataclass(frozen=True, slots=True)
class Source:
    name: str  # master_snapshots.source
    kind: Kind
    exchange: Exchange
    parse: Callable[[Sequence[Part]], Sequence[Row]]
    url: str  # 记录用的主 URL


SOURCES: Final[dict[str, Source]] = {
    s.name: s
    for s in (
        Source("sse_list", "list", "SH", parse_sse_list, SSE_QUERY),
        Source("sse_delist", "delist", "SH", parse_sse_delist, SSE_QUERY),
        Source("szse_list", "list", "SZ", parse_szse_list, szse_url("1110", "tab1")),
        Source("szse_delist", "delist", "SZ", parse_szse_delist, szse_url("1793_ssgs", "tab2")),
        Source("szse_rename", "rename", "SZ", parse_szse_rename, szse_url("SSGSGMXX", "tab2")),
        Source("bse_list", "list", "BJ", parse_bse_list, BSE_LIST_URL),
        Source("bse_code_map", "code_map", "BJ", parse_bse_code_map, BSE_CODE_MAP_URL),
    )
}
#: 每日同步的来源（北交所终止上市名单官网未找到批量接口，T007 §1 缺口；代码对照每月单独拉）
DAILY_SOURCES: Final = (
    "sse_list",
    "sse_delist",
    "szse_list",
    "szse_delist",
    "szse_rename",
    "bse_list",
)

#: fetcher(source_name) → 该来源的全部响应段。测试注入假实现；生产用 :func:`http_fetcher`。
Fetcher = Callable[[str], list[Part]]

_UA: Final = "Mozilla/5.0 (compatible; aia-master-sync/1)"
_TIMEOUT_S: Final = 60.0
_PAGE_PAUSE_S: Final = 0.5
_MAX_BYTES: Final = 32 * 1024 * 1024


def http_fetcher() -> Fetcher:  # pragma: no cover - 需要外网
    """标准库 urllib 实现（后端运行时依赖里没有 httpx）。

    北交所首个 POST 返回 307 并下发 cookie：urllib 不跟随 POST 的 307，这里带着 cookie jar
    手动重发一次。错误消息只含状态码 / 异常类型，不含响应正文。
    """
    import http.cookiejar
    import urllib.error
    import urllib.parse
    import urllib.request

    def fetch(source: str) -> list[Part]:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def get(url: str, *, data: dict[str, str] | None = None, referer: str = "") -> bytes:
            body = urllib.parse.urlencode(data).encode() if data is not None else None
            for attempt in range(2):
                req = urllib.request.Request(url, data=body)  # noqa: S310  固定 https 地址
                req.add_header("User-Agent", _UA)
                if referer:
                    req.add_header("Referer", referer)
                try:
                    with opener.open(req, timeout=_TIMEOUT_S) as resp:
                        content: bytes = resp.read(_MAX_BYTES + 1)
                except urllib.error.HTTPError as exc:
                    if exc.code in {307, 308} and attempt == 0:
                        loc = exc.headers.get("Location") or url
                        url = urllib.parse.urljoin(url, loc)
                        if not url.startswith("https://"):
                            raise FetchError("跳转到非 https 地址") from None
                        continue
                    raise FetchError(f"HTTP {exc.code}") from None
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    raise FetchError(f"请求失败：{type(exc).__name__}") from None
                if len(content) > _MAX_BYTES:
                    raise FetchError("响应过大")
                return content
            raise FetchError("重定向次数过多")

        if source == "sse_list":
            urls = [sse_list_url(t) for t in SSE_BOARDS]
            return [Part(u, get(u, referer=SSE_REFERER)) for u in urls]
        if source == "sse_delist":
            u = sse_delist_url()
            return [Part(u, get(u, referer=SSE_REFERER))]
        if source == "szse_list":
            return [Part(u, get(u)) for u in (szse_url("1110", t) for t in SZSE_LIST_TABS)]
        if source in {"szse_delist", "szse_rename", "bse_code_map"}:
            u = SOURCES[source].url
            return [Part(u, get(u))]
        if source == "bse_list":
            first = get(BSE_LIST_URL, data=bse_list_form(0))
            parts = [Part(bse_page_url(0), first)]
            for page in range(1, bse_total_pages(first)):
                time.sleep(_PAGE_PAUSE_S)
                parts.append(Part(bse_page_url(page), get(BSE_LIST_URL, data=bse_list_form(page))))
            return parts
        raise FetchError("未知来源")

    return fetch
