"""T-A22: additive source identity checks; no data rewrite/backfill.

Revision ID: 0023
Revises: 0022
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

OLD_SOURCES = (
    "sse_list",
    "sse_delist",
    "szse_list",
    "szse_delist",
    "szse_rename",
    "bse_list",
    "bse_delist",
    "bse_code_map",
    "cninfo",
    "akshare",
)
OLD_REASONS = ("exchange_list", "exchange_delist_list", "missing_from_list")


def _replace(table: str, name: str, column: str, values: tuple[str, ...]) -> None:
    # These names already exist verbatim in 0019; do not apply metadata
    # naming_convention (ck_<table>_<constraint_name>) a second time.
    op.drop_constraint(op.f(name), table, schema="market", type_="check")
    op.create_check_constraint(
        op.f(name),
        table,
        column + " IN (" + ",".join(repr(v) for v in values) + ")",
        schema="market",
    )


def upgrade() -> None:
    _replace(
        "master_snapshots", "ck_master_snapshots_source", "source", (*OLD_SOURCES, "mairui_list")
    )
    _replace(
        "security_listing_status_history",
        "ck_security_listing_status_history_reason",
        "reason",
        (*OLD_REASONS, "mairui_list"),
    )


def downgrade() -> None:
    # Fails transactionally if new-source rows still exist; never erase evidence.
    _replace(
        "security_listing_status_history",
        "ck_security_listing_status_history_reason",
        "reason",
        OLD_REASONS,
    )
    _replace("master_snapshots", "ck_master_snapshots_source", "source", OLD_SOURCES)
