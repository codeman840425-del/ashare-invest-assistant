"""Contract §7.3 read-only search over public master terms; never fetches upstream."""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import Connection, text

from app.common.errors import AppError, ErrorCode
from app.config_files import SecuritiesSearch
from app.schemas.enums import SecurityType

# Each match is ranked before deduplication; all filters apply before LIMIT.
_SEARCH = text("""
WITH eligible AS (
    SELECT * FROM market.securities
    WHERE type = ANY(:types)
      AND (:include_delisted OR listing_status IS DISTINCT FROM 'delisted')
), candidates AS (
    SELECT s.code, CASE WHEN left(s.code, 6) = :code_q THEN 0 ELSE 3 END AS rank,
           'code' AS term_kind, NULL::text AS source_name, 0 AS pos, 1.0::real AS sim
    FROM eligible s
    WHERE :code_q <> '' AND left(s.code, 6) LIKE :code_prefix ESCAPE '!'
      AND (:exchange = '' OR s.exchange = :exchange)
    UNION ALL
    SELECT t.code,
        CASE
          WHEN t.term_kind IN ('former_name', 'former_initials', 'former_code') THEN 7
          WHEN t.term_kind = 'name' AND t.term = :q THEN 1
          WHEN t.term_kind = 'name_initials' AND t.term = :q THEN 2
          WHEN t.term_kind = 'name' AND t.term LIKE :prefix ESCAPE '!' THEN 4
          WHEN t.term_kind = 'name_initials' THEN 5
          WHEN t.term_kind = 'name' AND strpos(t.term, :q) > 0 THEN 6
          ELSE 8
        END AS rank,
        t.term_kind, t.source_name, greatest(strpos(t.term, :q), 1) AS pos,
        similarity(t.term, :q) AS sim
    FROM market.security_search_terms t JOIN eligible s ON s.code = t.code
    WHERE
      (t.term_kind = 'name' AND (strpos(t.term, :q) > 0 OR
         (:fuzzy AND similarity(t.term, :q) >= :threshold)))
      OR (t.term_kind = 'name_initials' AND t.term LIKE :prefix ESCAPE '!')
      OR (t.term_kind = 'former_name' AND (strpos(t.term, :q) > 0 OR
         (:fuzzy AND similarity(t.term, :q) >= :threshold)))
      OR (t.term_kind = 'former_initials' AND t.term LIKE :prefix ESCAPE '!')
      OR (t.term_kind = 'former_code' AND :code_q <> '' AND EXISTS (
          SELECT 1 FROM market.security_code_history h
          WHERE h.code = t.code AND left(h.old_code, 6) = :code_q
            AND t.term IN (left(h.old_code, 6), h.old_code)
            AND (:exchange = '' OR right(h.old_code, 2) = :exchange)
      ))
), best AS (
    SELECT *, row_number() OVER (
      PARTITION BY code ORDER BY rank, pos, sim DESC, source_name, term_kind
    ) AS n FROM candidates
)
SELECT s.code AS security_code, s.name, s.type, s.exchange,
       CASE WHEN s.type IN ('index', 'etf') THEN NULL ELSE s.board END AS board,
       s.listing_status, s.risk_flag,
       CASE b.rank
         WHEN 0 THEN 'code_exact' WHEN 1 THEN 'name_exact' WHEN 2 THEN 'initials_exact'
         WHEN 3 THEN 'code_prefix' WHEN 4 THEN 'name_prefix' WHEN 5 THEN 'initials_prefix'
         WHEN 6 THEN 'name_contains'
         WHEN 7 THEN CASE WHEN b.term_kind = 'former_code' THEN 'former_code' ELSE 'former_name' END
         ELSE 'fuzzy' END AS match_kind,
       CASE WHEN b.term_kind IN ('name_initials', 'former_name', 'former_initials', 'former_code')
            THEN b.source_name ELSE NULL END AS matched_text,
       CASE WHEN s.type IN ('index', 'etf') OR NOT EXISTS (
           SELECT 1 FROM app.user_data_licence_status l
           JOIN market.master_vendor_batches v ON v.source_licence_id = l.id
           WHERE l.user_id = :user_id AND l.deleted_at IS NULL AND l.status = 'active'
             AND (l.paused_until IS NULL OR l.paused_until <= now())
             AND (l.expires_on IS NULL OR
                  l.expires_on >= (now() AT TIME ZONE 'Asia/Shanghai')::date)
             AND NOT EXISTS (
                 SELECT 1 FROM app.user_data_licence_holds h WHERE h.user_id = l.user_id
             )
             AND v.status = 'reconciled' AND v.reconciled_at IS NOT NULL
       ) THEN NULL ELSE EXISTS (
           SELECT 1 FROM market.security_reconciliation_diffs d
           JOIN app.user_data_licence_status l ON l.id = d.source_licence_id
           WHERE l.user_id = :user_id AND l.deleted_at IS NULL AND l.status = 'active'
             AND d.kind = 'quote_missing' AND d.source = 'mairui_lists'
             AND d.status = 'open' AND d.security_code = s.code
       ) END AS quote_missing
FROM best b JOIN eligible s ON s.code = b.code WHERE b.n = 1
ORDER BY b.rank,
    CASE s.listing_status WHEN 'listed' THEN 0 WHEN 'delisting_period' THEN 1 ELSE 2 END,
    CASE s.type WHEN 'stock' THEN 0 WHEN 'cdr' THEN 1 WHEN 'etf' THEN 2 ELSE 3 END,
    b.pos, length(s.name), b.sim DESC, s.code
LIMIT :limit
""")

_MASTER_DATE = text("""
SELECT DISTINCT ON (s.source) s.source, s.trade_date AS day
FROM market.master_snapshots s
JOIN market.master_runs r ON s.id = ANY(r.snapshot_ids)
WHERE s.source IN ('sse_list', 'szse_list', 'bse_list') AND s.parse_status = 'ok'
  AND r.finished_at IS NOT NULL AND r.status IN ('ok', 'partial')
  AND r.stats->'sources'->s.source->>'status' = 'ok'
ORDER BY s.source, r.started_at DESC, r.id DESC
""")


def invalid(field: str, issue: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR, details={"fields": [{"field": field, "issue": issue}]}
    )


def normalize(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).upper()


def search(
    conn: Connection,
    user_id: uuid.UUID,
    cfg: SecuritiesSearch,
    *,
    q: str,
    types: str,
    include_delisted: bool,
    limit: int | None,
) -> dict[str, Any]:
    query = normalize(q)
    if not 1 <= len(query) <= 20:
        raise invalid("q", "normalized length must be 1-20")
    selected_types = sorted(set(types.split(",")))
    if not selected_types or any(t not in {x.value for x in SecurityType} for t in selected_types):
        raise invalid("types", "unknown security type")
    count = cfg.limit_default if limit is None else limit
    if not 1 <= count <= min(cfg.limit_max, 50):
        raise invalid("limit", "out of range")
    dates = conn.execute(_MASTER_DATE).all()
    if len(dates) != 3:
        # plan §4.6.6 makes bootstrap a deployment prerequisite, never fake a date or issue 503.
        raise AppError(
            ErrorCode.INTERNAL_ERROR, details={"issue": "security_master_bootstrap_required"}
        )
    code = re.fullmatch(r"(?:(SH|SZ|BJ))?([0-9]{1,6})(?:\.(SH|SZ|BJ))?", query)
    digits, exchange = (code[2], code[1] or code[3] or "") if code else ("", "")
    if code and code[1] and code[3] and code[1] != code[3]:
        digits = ""
    escaped = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    rows = (
        conn.execute(
            _SEARCH,
            {
                "q": query,
                "prefix": escaped + "%",
                "code_q": digits,
                "code_prefix": digits + "%",
                "exchange": exchange,
                "types": selected_types,
                "include_delisted": include_delisted,
                "fuzzy": len(re.findall(r"[\u3400-\u9fff]", query)) >= 2,
                "threshold": cfg.similarity_threshold,
                "limit": count,
                "user_id": user_id,
            },
        )
        .mappings()
        .all()
    )
    return {
        "items": [dict(row) for row in rows],
        "master_as_of": min(row.day for row in dates).isoformat(),
    }
