from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import BurnoutResource, MotivationQuote, User
from schemas.misc import BurnoutResourceOut, QuoteOut
from utils.deps import get_current_user

router = APIRouter(prefix="/api/motivation", tags=["motivation"])


@router.get("/quote", response_model=QuoteOut)
async def random_quote(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(MotivationQuote).order_by(func.random()).limit(1))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No quotes seeded")
    return QuoteOut.model_validate(row)


@router.get("/resources", response_model=list[BurnoutResourceOut])
async def list_resources(
    category: str | None = None, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    stmt = select(BurnoutResource).order_by(BurnoutResource.category, BurnoutResource.title)
    if category and category != "All":
        stmt = stmt.where(BurnoutResource.category == category)
    rows = (await db.execute(stmt)).scalars().all()
    return [BurnoutResourceOut.model_validate(r) for r in rows]
