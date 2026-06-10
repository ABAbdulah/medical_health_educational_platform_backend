from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import get_db
from models import Question, QuestionAttempt, QuestionBookmark, QuestionOption, User
from schemas.question import AttemptIn, OptionOut, OptionReview, QuestionOut, QuestionReview
from utils.deps import get_current_user, is_premium

router = APIRouter(prefix="/api/questions", tags=["questions"])


async def _get_bookmark(db: AsyncSession, user_id: int, question_id: int) -> QuestionBookmark | None:
    return (
        await db.execute(
            select(QuestionBookmark).where(
                QuestionBookmark.user_id == user_id, QuestionBookmark.question_id == question_id
            )
        )
    ).scalar_one_or_none()


@router.get("")
async def list_questions(
    subject: str | None = None,
    difficulty: str | None = None,
    status: str | None = Query(default=None, pattern="^(unattempted|incorrect|bookmarked)?$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Question).where(Question.status == "published")
    if subject and subject != "All":
        stmt = stmt.where(Question.subject == subject)
    if difficulty and difficulty != "All":
        stmt = stmt.where(Question.difficulty == difficulty.lower())

    # latest attempt per question for this user
    attempts = (
        await db.execute(
            select(QuestionAttempt.question_id, QuestionAttempt.is_correct)
            .where(QuestionAttempt.user_id == user.id)
            .order_by(QuestionAttempt.attempted_at)
        )
    ).all()
    last_result: dict[int, bool] = {qid: ok for qid, ok in attempts}

    bookmarks = {
        r[0]
        for r in (
            await db.execute(
                select(QuestionBookmark.question_id).where(QuestionBookmark.user_id == user.id)
            )
        ).all()
    }

    rows = (await db.execute(stmt.order_by(Question.qid))).scalars().all()
    items = []
    for q in rows:
        attempted = q.id in last_result
        if status == "unattempted" and attempted:
            continue
        if status == "incorrect" and (not attempted or last_result[q.id]):
            continue
        if status == "bookmarked" and q.id not in bookmarks:
            continue
        items.append(
            {
                "id": q.id, "qid": q.qid, "subject": q.subject, "topic": q.topic,
                "difficulty": q.difficulty, "attempted": attempted,
                "last_correct": last_result.get(q.id), "bookmarked": q.id in bookmarks,
            }
        )

    total = len(items)
    start = (page - 1) * page_size
    return {"total": total, "page": page, "page_size": page_size, "items": items[start : start + page_size]}


@router.get("/{question_id}", response_model=QuestionOut)
async def get_question(question_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    q = (
        await db.execute(
            select(Question).options(selectinload(Question.options)).where(Question.id == question_id)
        )
    ).scalar_one_or_none()
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    bm = await _get_bookmark(db, user.id, q.id)
    out = QuestionOut(
        id=q.id, qid=q.qid, subject=q.subject, topic=q.topic, difficulty=q.difficulty,
        question_text=q.question_text,
        options=[OptionOut.model_validate(o) for o in q.options],
        bookmarked=bm is not None, flagged=bool(bm and bm.flagged),
    )
    return out


@router.post("/{question_id}/attempt", response_model=QuestionReview)
async def attempt_question(
    question_id: int,
    payload: AttemptIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not is_premium(user):
        start_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        count_today = (
            await db.execute(
                select(func.count(QuestionAttempt.id)).where(
                    QuestionAttempt.user_id == user.id, QuestionAttempt.attempted_at >= start_today
                )
            )
        ).scalar() or 0
        if count_today >= settings.FREE_DAILY_MCQ_LIMIT:
            raise HTTPException(
                status_code=402,
                detail=f"Free plan is limited to {settings.FREE_DAILY_MCQ_LIMIT} MCQs per day. Upgrade for unlimited access.",
            )

    q = (
        await db.execute(
            select(Question).options(selectinload(Question.options)).where(Question.id == question_id)
        )
    ).scalar_one_or_none()
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")

    correct_option = next((o for o in q.options if o.is_correct), None)
    if correct_option is None:
        raise HTTPException(status_code=500, detail="Question has no correct answer configured")
    is_correct = payload.selected_letter == correct_option.letter

    db.add(
        QuestionAttempt(
            user_id=user.id, question_id=q.id, selected_letter=payload.selected_letter,
            is_correct=is_correct, time_taken_seconds=payload.time_taken_seconds,
        )
    )
    await db.commit()

    # population stats: percentage who chose each option
    rows = (
        await db.execute(
            select(QuestionAttempt.selected_letter, func.count(QuestionAttempt.id))
            .where(QuestionAttempt.question_id == q.id)
            .group_by(QuestionAttempt.selected_letter)
        )
    ).all()
    counts = {letter: n for letter, n in rows}
    total = sum(counts.values()) or 1

    return QuestionReview(
        id=q.id, qid=q.qid, subject=q.subject, topic=q.topic, difficulty=q.difficulty,
        question_text=q.question_text,
        options=[
            OptionReview(
                id=o.id, letter=o.letter, text=o.text, is_correct=o.is_correct,
                explanation=o.explanation,
                pct_chosen=round(counts.get(o.letter, 0) / total * 100, 0),
            )
            for o in q.options
        ],
        explanation=q.explanation, learning_point=q.learning_point,
        reference_source=q.reference_source, updated_at=q.updated_at,
        correct_letter=correct_option.letter, selected_letter=payload.selected_letter,
        is_correct=is_correct, time_taken_seconds=payload.time_taken_seconds,
    )


@router.post("/{question_id}/bookmark")
async def toggle_bookmark(
    question_id: int,
    flag: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bm = await _get_bookmark(db, user.id, question_id)
    if bm is None:
        db.add(QuestionBookmark(user_id=user.id, question_id=question_id, flagged=flag))
        result = {"bookmarked": True, "flagged": flag}
    elif flag and not bm.flagged:
        bm.flagged = True
        result = {"bookmarked": True, "flagged": True}
    else:
        await db.delete(bm)
        result = {"bookmarked": False, "flagged": False}
    await db.commit()
    return result


@router.get("/meta/stats")
async def question_stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count(Question.id)))).scalar() or 0
    attempted = (
        await db.execute(
            select(func.count(func.distinct(QuestionAttempt.question_id))).where(
                QuestionAttempt.user_id == user.id
            )
        )
    ).scalar() or 0
    correct = (
        await db.execute(
            select(func.count(QuestionAttempt.id)).where(
                QuestionAttempt.user_id == user.id, QuestionAttempt.is_correct.is_(True)
            )
        )
    ).scalar() or 0
    all_attempts = (
        await db.execute(select(func.count(QuestionAttempt.id)).where(QuestionAttempt.user_id == user.id))
    ).scalar() or 0
    return {
        "total_questions": total,
        "attempted": attempted,
        "accuracy": round(correct / all_attempts * 100, 1) if all_attempts else 0.0,
    }
