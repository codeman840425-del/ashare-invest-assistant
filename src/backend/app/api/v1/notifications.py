"""Contract §7.8 static count route; no fabricated notification/list implementation."""

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.auth.deps import AuthDep, EngineDep
from app.db.tables.notify import notifications

router = APIRouter(tags=["notifications"])


class UnreadCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(strict=True, ge=0)


# Register static routes before any future /notifications/{id} route.
@router.get("/notifications/unread-count")
def unread_count(auth: AuthDep, engine: EngineDep, response: Response) -> UnreadCount:
    response.headers["Cache-Control"] = "private, no-store"
    with engine.connect() as conn:
        count = conn.execute(
            select(func.count())
            .select_from(notifications)
            .where(
                notifications.c.user_id == auth.user_id,
                notifications.c.read_at.is_(None),
            )
        ).scalar_one()
    return UnreadCount(count=int(count))
