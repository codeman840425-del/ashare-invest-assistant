"""T-B61b 聚合not_set：不回填、不伪造UUID、不删除证据。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "master_vendor_batches",
        "source_licence_id",
        existing_type=UUID(),
        nullable=True,
        schema="market",
    )
    op.create_check_constraint(
        op.f("ck_master_vendor_batches_not_set_scope"),
        "master_vendor_batches",
        "source_licence_id IS NOT NULL OR (status = 'skipped' AND attempt = 1 AND error_code IS NOT NULL AND error_code = 'licence_unavailable')",
        schema="market",
    )
    op.create_index(
        "ux_master_vendor_batches_not_set",
        "master_vendor_batches",
        ["master_run_id", "attempt"],
        unique=True,
        schema="market",
        postgresql_where=sa.text("source_licence_id IS NULL"),
    )


def downgrade() -> None:
    count = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM market.master_vendor_batches WHERE source_licence_id IS NULL"
            )
        )
        .scalar_one()
    )
    if count:
        raise RuntimeError(f"存在{count}条聚合not_set批次，拒绝降级，不删除或伪造归属")
    op.drop_index(
        "ux_master_vendor_batches_not_set", table_name="master_vendor_batches", schema="market"
    )
    op.drop_constraint(
        op.f("ck_master_vendor_batches_not_set_scope"),
        "master_vendor_batches",
        schema="market",
        type_="check",
    )
    op.alter_column(
        "master_vendor_batches",
        "source_licence_id",
        existing_type=UUID(),
        nullable=False,
        schema="market",
    )
