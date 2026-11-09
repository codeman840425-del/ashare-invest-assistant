"""Private ingest binding tags and non-secret scope history (T-B99e/R3A)."""

from sqlalchemy import Column, ForeignKey, Index, LargeBinary, Table
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import metadata, pk_uuid, ts

PRIVATE = "ingest_private"

mairui_gate_scopes = Table(
    "mairui_gate_scopes",
    metadata,
    pk_uuid(),
    Column("origin_licence_id", UUID(as_uuid=True), nullable=False),
    ts("detached_at"),
    schema=PRIVATE,
)
mairui_gate_bindings = Table(
    "mairui_gate_bindings",
    metadata,
    Column(
        "licence_id",
        UUID(as_uuid=True),
        ForeignKey("app.user_data_licences.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("app.users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "scope_id",
        UUID(as_uuid=True),
        ForeignKey("ingest_private.mairui_gate_scopes.id"),
        nullable=False,
    ),
    Column("tag", LargeBinary(), nullable=False),
    ts("expires_at"),
    schema=PRIVATE,
)
Index(
    "ix_mairui_gate_bindings_user_tag", mairui_gate_bindings.c.user_id, mairui_gate_bindings.c.tag
)
