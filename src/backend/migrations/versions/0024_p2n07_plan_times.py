"""P2N-07 plan transition timestamps; immutable version body remains in completeness."""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "action_plans",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="app",
    )
    op.add_column(
        "action_plans", sa.Column("triggered_at", sa.DateTime(timezone=True)), schema="app"
    )
    op.add_column("alerts", sa.Column("handled_at", sa.DateTime(timezone=True)), schema="app")


def downgrade() -> None:
    op.drop_column("alerts", "handled_at", schema="app")
    op.drop_column("action_plans", "triggered_at", schema="app")
    op.drop_column("action_plans", "updated_at", schema="app")
