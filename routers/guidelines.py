from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import GuidelineTopic, User
from schemas.misc import GuidelineTopicOut
from utils.deps import get_current_user

router = APIRouter(prefix="/api/guidelines", tags=["guidelines"])


@router.get("/topics", response_model=list[GuidelineTopicOut])
async def list_topics(
    q: str | None = Query(default=None, max_length=200),
    subject: str | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(GuidelineTopic).order_by(GuidelineTopic.topic_name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                GuidelineTopic.topic_name.ilike(like),
                GuidelineTopic.summary.ilike(like),
                GuidelineTopic.diagnosis.ilike(like),
                GuidelineTopic.management.ilike(like),
            )
        )
    if subject and subject != "All":
        stmt = stmt.where(GuidelineTopic.subject == subject)
    rows = (await db.execute(stmt.limit(100))).scalars().all()
    return [GuidelineTopicOut.model_validate(r) for r in rows]


@router.get("/topics/{topic_id}", response_model=GuidelineTopicOut)
async def topic_detail(topic_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    topic = await db.get(GuidelineTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return GuidelineTopicOut.model_validate(topic)
