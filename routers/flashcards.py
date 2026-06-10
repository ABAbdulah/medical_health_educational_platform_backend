from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Flashcard, FlashcardProgress, User
from schemas.misc import FlashcardIn, FlashcardOut, FlashcardReviewIn, FlashcardUpdate
from services.sm2 import schedule_review
from utils.deps import get_current_user

router = APIRouter(prefix="/api/flashcards", tags=["flashcards"])


@router.get("", response_model=list[FlashcardOut])
async def list_flashcards(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Flashcard).where(Flashcard.user_id == user.id).order_by(Flashcard.created_at.desc())
        )
    ).scalars().all()
    return [FlashcardOut.model_validate(f) for f in rows]


@router.post("", response_model=FlashcardOut, status_code=201)
async def create_flashcard(
    payload: FlashcardIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    card = Flashcard(user_id=user.id, **payload.model_dump())
    db.add(card)
    await db.flush()
    db.add(FlashcardProgress(flashcard_id=card.id, user_id=user.id, next_review_date=date.today()))
    await db.commit()
    await db.refresh(card)
    return FlashcardOut.model_validate(card)


@router.get("/due")
async def due_flashcards(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Flashcard, FlashcardProgress)
            .join(FlashcardProgress, FlashcardProgress.flashcard_id == Flashcard.id)
            .where(FlashcardProgress.user_id == user.id, FlashcardProgress.next_review_date <= date.today())
            .order_by(FlashcardProgress.next_review_date)
        )
    ).all()
    return [
        {
            "id": card.id, "front_text": card.front_text, "back_text": card.back_text,
            "subject": card.subject, "difficulty": card.difficulty,
            "personal_notes": card.personal_notes, "repetitions": prog.repetitions,
        }
        for card, prog in rows
    ]


@router.put("/{card_id}", response_model=FlashcardOut)
async def update_flashcard(
    card_id: int,
    payload: FlashcardUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    card = (
        await db.execute(select(Flashcard).where(Flashcard.id == card_id, Flashcard.user_id == user.id))
    ).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(card, field, value)
    await db.commit()
    await db.refresh(card)
    return FlashcardOut.model_validate(card)


@router.post("/{card_id}/review")
async def review_flashcard(
    card_id: int,
    payload: FlashcardReviewIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prog = (
        await db.execute(
            select(FlashcardProgress).where(
                FlashcardProgress.flashcard_id == card_id, FlashcardProgress.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if prog is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")
    update = schedule_review(payload.rating, prog.ease_factor, prog.interval_days, prog.repetitions)
    prog.ease_factor = update["ease_factor"]
    prog.interval_days = update["interval_days"]
    prog.repetitions = update["repetitions"]
    prog.next_review_date = update["next_review_date"]
    prog.last_reviewed = datetime.now(timezone.utc)
    await db.commit()
    return {"next_review_date": prog.next_review_date.isoformat(), "interval_days": prog.interval_days}


@router.delete("/{card_id}", status_code=204)
async def delete_flashcard(card_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    card = (
        await db.execute(select(Flashcard).where(Flashcard.id == card_id, Flashcard.user_id == user.id))
    ).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found")
    await db.delete(card)
    await db.commit()


@router.get("/stats")
async def flashcard_stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    total = (
        await db.execute(select(func.count(Flashcard.id)).where(Flashcard.user_id == user.id))
    ).scalar() or 0
    due = (
        await db.execute(
            select(func.count(FlashcardProgress.id)).where(
                FlashcardProgress.user_id == user.id, FlashcardProgress.next_review_date <= date.today()
            )
        )
    ).scalar() or 0
    return {"total": total, "due": due}
