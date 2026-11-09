"""T-A52: retain settings identity/history while clearing user overrides."""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = depends_on = None


def upgrade() -> None:
    op.add_column(
        "risk_control_settings",
        sa.Column("override_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("risk_control_settings", "override_active", schema="app")
