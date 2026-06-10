from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import (
    FlashcardProgress, MotivationQuote, Question, QuestionAttempt,
    RecallTopic, StudyPlan, StudyTask, User,
)
from utils.deps import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

DAILY_MCQ_TARGET = 20


async def compute_readiness(db: AsyncSession, user_id: int) -> float:
    """Readiness = 60% MCQ accuracy + 40% topic coverage."""
    total_attempts = (
        await db.execute(select(func.count(QuestionAttempt.id)).where(QuestionAttempt.user_id == user_id))
    ).scalar() or 0
    correct = (
        await db.execute(
            select(func.count(QuestionAttempt.id)).where(
                QuestionAttempt.user_id == user_id, QuestionAttempt.is_correct.is_(True)
            )
        )
    ).scalar() or 0
    accuracy = correct / total_attempts if total_attempts else 0.0

    topics_attempted = (
        await db.execute(
            select(func.count(distinct(Question.topic)))
            .join(QuestionAttempt, QuestionAttempt.question_id == Question.id)
            .where(QuestionAttempt.user_id == user_id)
        )
    ).scalar() or 0
    total_topics = (await db.execute(select(func.count(distinct(Question.topic))))).scalar() or 1
    coverage = topics_attempted / total_topics

    return round((accuracy * 0.6 + coverage * 0.4) * 100, 1)


@router.get("/summary")
async def dashboard_summary(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    today = date.today()

    plan = (
        await db.execute(
            select(StudyPlan)
            .where(StudyPlan.user_id == user.id, StudyPlan.status == "active")
            .order_by(StudyPlan.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    today_tasks: list[dict] = []
    upcoming: list[dict] = []
    if plan:
        tasks = (
            await db.execute(
                select(StudyTask)
                .where(StudyTask.plan_id == plan.id, StudyTask.due_date == today)
                .order_by(StudyTask.task_type)
            )
        ).scalars().all()
        today_tasks = [
            {
                "id": t.id, "subject": t.subject, "topic": t.topic, "task_type": t.task_type,
                "estimated_hours": t.estimated_hours, "completed": t.completed,
            }
            for t in tasks
        ]
        upcoming_rows = (
            await db.execute(
                select(StudyTask)
                .where(
                    StudyTask.plan_id == plan.id,
                    StudyTask.task_type == "revision",
                    StudyTask.due_date > today,
                    StudyTask.completed.is_(False),
                )
                .order_by(StudyTask.due_date)
                .limit(3)
            )
        ).scalars().all()
        upcoming = [
            {"id": t.id, "subject": t.subject, "topic": t.topic, "due_date": t.due_date.isoformat()}
            for t in upcoming_rows
        ]

    start_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    mcqs_today = (
        await db.execute(
            select(func.count(QuestionAttempt.id)).where(
                QuestionAttempt.user_id == user.id, QuestionAttempt.attempted_at >= start_today
            )
        )
    ).scalar() or 0

    quote_row = (
        await db.execute(select(MotivationQuote).order_by(func.random()).limit(1))
    ).scalar_one_or_none()

    # subject x month recall heatmap (top 5 subjects, last 6 months)
    heatmap_rows = (
        await db.execute(
            select(
                RecallTopic.subject,
                func.to_char(RecallTopic.detected_at, "YYYY-MM").label("month"),
                func.sum(RecallTopic.frequency),
            )
            .group_by(RecallTopic.subject, "month")
            .order_by(func.sum(RecallTopic.frequency).desc())
            .limit(40)
        )
    ).all()
    heatmap = [{"subject": r[0], "month": r[1], "frequency": int(r[2])} for r in heatmap_rows]

    due_flashcards = (
        await db.execute(
            select(func.count(FlashcardProgress.id)).where(
                FlashcardProgress.user_id == user.id, FlashcardProgress.next_review_date <= today
            )
        )
    ).scalar() or 0

    readiness = await compute_readiness(db, user.id)
    if plan and plan.readiness_score != readiness:
        plan.readiness_score = readiness
        await db.commit()

    return {
        "today_tasks": today_tasks,
        "mcq_today": mcqs_today,
        "mcq_target": DAILY_MCQ_TARGET,
        "readiness_score": readiness,
        "upcoming_revision": upcoming,
        "quote": {"quote": quote_row.quote, "author": quote_row.author} if quote_row else None,
        "recall_heatmap": heatmap,
        "due_flashcards": due_flashcards,
        "exam_date": plan.target_exam_date.isoformat() if plan else None,
        "days_to_exam": (plan.target_exam_date - today).days if plan else None,
        "subscription_status": user.subscription_status,
        "limits": {
            "free_daily_mcq": settings.FREE_DAILY_MCQ_LIMIT,
            "free_daily_ai": settings.FREE_DAILY_AI_LIMIT,
        },
    }
