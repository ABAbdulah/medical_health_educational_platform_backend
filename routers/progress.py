from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Question, QuestionAttempt, StudyPlan, StudyTask, User
from routers.dashboard import compute_readiness
from utils.deps import get_current_user

router = APIRouter(prefix="/api/progress", tags=["progress"])

SUBJECTS = ["Medicine", "Surgery", "Paediatrics", "OBGYN", "Psychiatry", "Ethics", "Emergency"]


@router.get("/overview")
async def progress_overview(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=6)

    # study hours this week from completed tasks
    plan = (
        await db.execute(
            select(StudyPlan)
            .where(StudyPlan.user_id == user.id, StudyPlan.status == "active")
            .order_by(StudyPlan.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    hours_by_day = {(week_start + timedelta(days=i)).date().isoformat(): 0.0 for i in range(7)}
    if plan:
        rows = (
            await db.execute(
                select(StudyTask).where(
                    StudyTask.plan_id == plan.id,
                    StudyTask.completed.is_(True),
                    StudyTask.completed_at >= week_start,
                )
            )
        ).scalars().all()
        for t in rows:
            key = t.completed_at.date().isoformat()
            if key in hours_by_day:
                hours_by_day[key] += t.estimated_hours

    # accuracy by subject (radar)
    radar = []
    for subject in SUBJECTS:
        total = (
            await db.execute(
                select(func.count(QuestionAttempt.id))
                .join(Question, Question.id == QuestionAttempt.question_id)
                .where(QuestionAttempt.user_id == user.id, Question.subject == subject)
            )
        ).scalar() or 0
        correct = (
            await db.execute(
                select(func.count(QuestionAttempt.id))
                .join(Question, Question.id == QuestionAttempt.question_id)
                .where(
                    QuestionAttempt.user_id == user.id,
                    Question.subject == subject,
                    QuestionAttempt.is_correct.is_(True),
                )
            )
        ).scalar() or 0
        radar.append(
            {"subject": subject, "accuracy": round(correct / total * 100, 1) if total else 0, "attempts": total}
        )

    # topics covered (donut)
    covered = (
        await db.execute(
            select(func.count(distinct(Question.topic)))
            .join(QuestionAttempt, QuestionAttempt.question_id == Question.id)
            .where(QuestionAttempt.user_id == user.id)
        )
    ).scalar() or 0
    total_topics = (await db.execute(select(func.count(distinct(Question.topic))))).scalar() or 0

    # streak: consecutive days with any attempt or completed task
    attempt_days = {
        r[0].date() if isinstance(r[0], datetime) else r[0]
        for r in (
            await db.execute(
                select(func.date(QuestionAttempt.attempted_at).label("day"))
                .where(QuestionAttempt.user_id == user.id)
                .distinct()
            )
        ).all()
    }
    streak = 0
    day = date.today()
    while day in attempt_days:
        streak += 1
        day -= timedelta(days=1)

    weakest = sorted([r for r in radar if r["attempts"] > 0], key=lambda r: r["accuracy"])[:3]

    return {
        "study_hours_week": [{"date": k, "hours": round(v, 1)} for k, v in sorted(hours_by_day.items())],
        "accuracy_by_subject": radar,
        "topics_completed": {"covered": covered, "total": total_topics},
        "readiness_score": await compute_readiness(db, user.id),
        "weakest_subjects": weakest,
        "streak_days": streak,
        "plan_completion_pct": plan.completion_pct if plan else 0.0,
    }


@router.get("/readiness-history")
async def readiness_history(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Approximate readiness trend: cumulative accuracy per week over last 8 weeks."""
    points = []
    now = datetime.now(timezone.utc)
    for weeks_back in range(7, -1, -1):
        cutoff = now - timedelta(weeks=weeks_back)
        total = (
            await db.execute(
                select(func.count(QuestionAttempt.id)).where(
                    QuestionAttempt.user_id == user.id, QuestionAttempt.attempted_at <= cutoff
                )
            )
        ).scalar() or 0
        correct = (
            await db.execute(
                select(func.count(QuestionAttempt.id)).where(
                    QuestionAttempt.user_id == user.id,
                    QuestionAttempt.attempted_at <= cutoff,
                    QuestionAttempt.is_correct.is_(True),
                )
            )
        ).scalar() or 0
        points.append(
            {
                "week": cutoff.date().isoformat(),
                "score": round(correct / total * 100, 1) if total else 0,
            }
        )
    return {"points": points}
