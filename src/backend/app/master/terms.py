"""Contract §7.3 / plan §4.6.3 public master terms; no network or credential access."""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from pypinyin import Style, lazy_pinyin, pinyin
from sqlalchemy import Connection, delete, insert, select, text

from app.db.tables.market import (
    securities,
    security_code_history,
    security_name_history,
    security_search_terms,
)
from app.master.search import normalize

GENERATOR_VERSION = 1


def _initial_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize(value))


def initials(value: str, maximum: int = 16) -> list[str]:
    if maximum < 1:
        raise ValueError("initials maximum must be positive")
    maximum = min(maximum, 16)
    # Phrase dictionary reading always occupies rank zero, even if the product is capped.
    default = _initial_text(
        "".join(
            lazy_pinyin(
                value,
                style=Style.FIRST_LETTER,
                strict=False,
                errors=lambda chunk: list(chunk),
            )
        )
    )
    result = [default] if default else []
    choices = []
    for character in value:
        readings = pinyin(
            character,
            style=Style.FIRST_LETTER,
            heteronym=True,
            strict=False,
            errors=lambda chunk: list(chunk),
        )
        choices.append(list(dict.fromkeys(_initial_text(item) for item in readings[0])))
    for combination in itertools.product(*choices):
        candidate = "".join(combination)
        if candidate and candidate not in result:
            result.append(candidate)
        if len(result) >= maximum:
            break
    return result[:maximum]


@dataclass(frozen=True, order=True)
class Term:
    term_kind: str
    term: str
    source_name: str
    is_st_stripped: bool = False
    variant_rank: int = 0
    generator_version: int = GENERATOR_VERSION


def generate(
    name: str, former_names: Sequence[str] = (), old_codes: Sequence[str] = (), *, maximum: int = 16
) -> list[Term]:
    """Only five declared kinds; code search reads securities directly, full names are excluded."""
    terms: dict[tuple[str, str, str], Term] = {}

    def add(term: Term) -> None:
        key = term.term_kind, term.term, term.source_name
        previous = terms.get(key)
        if previous is None or (term.is_st_stripped, term.variant_rank) < (
            previous.is_st_stripped,
            previous.variant_rank,
        ):
            terms[key] = term

    names = [(name, False)] + [
        (old, True) for old in former_names if normalize(old) != normalize(name)
    ]
    for source, former in names:
        current = normalize(source)
        if not current:
            continue
        stripped = re.sub(r"^(?:\*?ST|S|退)+", "", current)
        variants = [(current, False)]
        if stripped and stripped != current:
            variants.append((stripped, True))
        for value, is_stripped in variants:
            add(Term("former_name" if former else "name", value, source, is_stripped))
            for rank, letters in enumerate(initials(value, maximum)):
                add(
                    Term(
                        "former_initials" if former else "name_initials",
                        letters,
                        source,
                        is_stripped,
                        rank,
                    )
                )
    for code in old_codes:
        if not re.fullmatch(r"[0-9]{6}\.BJ", code):
            raise ValueError("invalid former BSE code")
        add(Term("former_code", code[:6], code))
    return sorted(terms.values())


def rebuild(
    conn: Connection, codes: Sequence[str] | None = None, *, maximum: int = 16
) -> dict[str, int]:
    """Rebuild selected public master rows in the caller's transaction; idempotent, no commit."""
    if codes is not None and any(not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code) for code in codes):
        raise ValueError("invalid security code")
    if maximum < 1:
        raise ValueError("initials maximum must be positive")
    query = select(securities.c.code, securities.c.name)
    if codes is not None:
        query = query.where(securities.c.code.in_(sorted(set(codes))))
    master = conn.execute(query.order_by(securities.c.code).with_for_update()).all()
    result = {"securities": len(master), "changed_securities": 0, "terms": 0}
    for row in master:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:code,202603))"), {"code": row.code}
        )
        former_names = (
            conn.execute(
                select(security_name_history.c.name)
                .where(
                    security_name_history.c.code == row.code,
                )
                .distinct()
            )
            .scalars()
            .all()
        )
        old_codes = (
            conn.execute(
                select(security_code_history.c.old_code).where(
                    security_code_history.c.code == row.code,
                )
            )
            .scalars()
            .all()
        )
        expected = generate(row.name, former_names, old_codes, maximum=maximum)
        result["terms"] += len(expected)
        existing = conn.execute(
            select(
                security_search_terms.c.term_kind,
                security_search_terms.c.term,
                security_search_terms.c.source_name,
                security_search_terms.c.is_st_stripped,
                security_search_terms.c.variant_rank,
                security_search_terms.c.generator_version,
            ).where(security_search_terms.c.code == row.code)
        ).all()
        if sorted(Term(*item) for item in existing) == expected:
            continue
        conn.execute(delete(security_search_terms).where(security_search_terms.c.code == row.code))
        if expected:
            conn.execute(
                insert(security_search_terms),
                [dict(code=row.code, **asdict(term)) for term in expected],
            )
        result["changed_securities"] += 1
    return result
