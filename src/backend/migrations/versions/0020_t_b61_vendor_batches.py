"""T-B61 对账批次交接（plan §4.6.5A），不灌数据、不授予运行角色DDL。"""

from alembic import op
from sqlalchemy import select

from app.db.tables.vendor import master_vendor_batches, master_vendor_list_rows

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    master_vendor_batches.create(op.get_bind())
    master_vendor_list_rows.create(op.get_bind())


def downgrade() -> None:
    conn = op.get_bind()
    for table in (master_vendor_list_rows, master_vendor_batches):
        if conn.execute(select(table).limit(1)).first() is not None:
            raise RuntimeError("对账批次表仍有数据，拒绝降级，不自动删除")
    master_vendor_list_rows.drop(conn)
    master_vendor_batches.drop(conn)
