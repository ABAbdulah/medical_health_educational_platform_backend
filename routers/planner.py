from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import StudyPlan, StudyTask, User, UserPreferences
from schemas.misc import CustomTaskIn, StudyPlanOut, StudyTaskOut
from services.planner_service import generate_plan_tasks
from utils.deps import get_current_user

router = APIRouter(prefix="/api/planner", tags=["planner"])


@router.post("/generate", response_model=StudyPlanOut, status_code=201)
async def generate_plan(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    prefs = (
        await db.execute(select(UserPreferences).where(UserPreferences.user_id == user.id))
    ).scalar_one_or_none()
    if prefs is None or prefs.exam_date is None:
        raise HTTPException(status_code=400, detail="Complete your profile setup (exam date) first")
    if prefs.exam_date <= date.today():
        raise HTTPException(status_code=400, detail="Exam date must be in the future")

    # archive previous active plans
    await db.execute(
        update(StudyPlan)
        .where(StudyPlan.user_id == user.id, StudyPlan.status == "active")
        .values(status="archived")
    )

    plan = StudyPlan(user_id=user.id, target_exam_date=prefs.exam_date)
    db.add(plan)
    await db.flush()

    tasks = generate_plan_tasks(
        exam_date=prefs.exam_date,
        daily_hours=prefs.daily_hours or 4.0,
        working_status=user.working_status,
        strong_subjects=prefs.strong_subjects or [],
        weak_subjects=prefs.weak_subjects or [],
    )
    db.add_all(StudyTask(plan_id=plan.id, **t) for t in tasks)
    await db.commit()
    await db.refresh(plan)
    return StudyPlanOut.model_validate(plan)


@router.get("/current")
async def current_plan(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    plan = (
        await db.execute(
            select(StudyPlan)
            .where(StudyPlan.user_id == user.id, StudyPlan.status == "active")
            .order_by(StudyPlan.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if plan is None:
        return {"plan": None, "tasks": []}
    tasks = (
        await db.execute(select(StudyTask).where(StudyTask.plan_id == plan.id).order_by(StudyTask.due_date))
    ).scalars().all()
    return {
        "plan": StudyPlanOut.model_validate(plan).model_dump(),
        "tasks": [StudyTaskOut.model_validate(t).model_dump() for t in tasks],
    }


@router.post("/tasks", response_model=StudyTaskOut, status_code=201)
async def add_custom_task(
    payload: CustomTaskIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Add a user-created task (dashboard '+ Add Task' / guidelines 'Add to Study Plan').

    If no active plan exists yet, a minimal plan is created to hold custom tasks.
    """
    plan = (
        await db.execute(
            select(StudyPlan)
            .where(StudyPlan.user_id == user.id, StudyPlan.status == "active")
            .order_by(StudyPlan.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if plan is None:
        prefs = (
            await db.execute(select(UserPreferences).where(UserPreferences.user_id == user.id))
        ).scalar_one_or_none()
        target = prefs.exam_date if prefs and prefs.exam_date and prefs.exam_date > date.today() else payload.due_date
        plan = StudyPlan(user_id=user.id, target_exam_date=target)
        db.add(plan)
        await db.flush()

    task = StudyTask(
        plan_id=plan.id,
        subject=payload.subject,
        topic=payload.topic,
        estimated_hours=payload.estimated_hours,
        due_date=payload.due_date,
        task_type=payload.task_type,
    )
    db.add(task)

    # adding a task changes the completion denominator
    plan_tasks = (
        await db.execute(select(StudyTask).where(StudyTask.plan_id == plan.id))
    ).scalars().all()
    done = sum(1 for t in plan_tasks if t.completed)
    plan.completion_pct = round(done / (len(plan_tasks) + 1) * 100, 1)

    await db.commit()
    await db.refresh(task)
    return StudyTaskOut.model_validate(task)


@router.patch("/tasks/{task_id}/toggle", response_model=StudyTaskOut)
async def toggle_task(task_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = (
        await db.execute(
            select(StudyTask)
            .join(StudyPlan, StudyPlan.id == StudyTask.plan_id)
            .where(StudyTask.id == task_id, StudyPlan.user_id == user.id)
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    task.completed = not task.completed
    task.completed_at = datetime.now(timezone.utc) if task.completed else None

    # refresh plan completion percentage
    plan_tasks = (
        await db.execute(select(StudyTask).where(StudyTask.plan_id == task.plan_id))
    ).scalars().all()
    done = sum(1 for t in plan_tasks if t.completed)
    plan = await db.get(StudyPlan, task.plan_id)
    if plan:
        plan.completion_pct = round(done / len(plan_tasks) * 100, 1) if plan_tasks else 0.0
    await db.commit()
    await db.refresh(task)
    return StudyTaskOut.model_validate(task)
