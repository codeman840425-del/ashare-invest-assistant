"""T-A13 add-only nullable display metadata; independent of paused 0021 WIP.

Apply this revision explicitly, not all heads. No backfill or promotion.
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0020"
branch_labels = ("ta13_features",)
depends_on = None


def upgrade() -> None:
    op.add_column("feature_catalog", sa.Column("dimension", sa.Text(), nullable=True), schema="app")
    op.add_column(
        "feature_catalog", sa.Column("warmup_bars", sa.Integer(), nullable=True), schema="app"
    )
    op.add_column(
        "feature_catalog", sa.Column("epistemic_type", sa.Text(), nullable=True), schema="app"
    )


def downgrade() -> None:
    for name in ("epistemic_type", "warmup_bars", "dimension"):
        op.drop_column("feature_catalog", name, schema="app")
