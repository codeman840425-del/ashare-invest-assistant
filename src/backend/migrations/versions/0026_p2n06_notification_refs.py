"""T-A28 unique event references, no external delivery or invented history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("notification_refs_rollback", schema="app"):
        op.rename_table("notification_refs_rollback", "notification_refs", schema="app")
        return
    op.create_table(
        "notification_refs",
        sa.Column(
            "notification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.notifications.id"),
            nullable=False,
        ),
        sa.Column("ref_type", sa.Text(), nullable=False),
        sa.Column("ref_id", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("notification_id", "ref_type", "ref_id"),
        sa.CheckConstraint("ref_type IN ('signal', 'plan_condition')", name="ref_type_enum"),
        schema="app",
    )


def downgrade() -> None:
    op.rename_table("notification_refs", "notification_refs_rollback", schema="app")
