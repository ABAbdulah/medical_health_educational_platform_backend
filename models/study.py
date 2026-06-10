from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class StudyPlan(Base):
    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    target_exam_date: Mapped[date] = mapped_column(Date)
    completion_pct: Mapped[float] = mapped_column(Float, default=0.0)
    readiness_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | archived

    tasks: Mapped[list["StudyTask"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class StudyTask(Base):
    __tablename__ = "study_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plans.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(100))
    topic: Mapped[str] = mapped_column(String(255))
    task_type: Mapped[str] = mapped_column(String(30), default="study")  # study | revision | mock_exam | mcq_practice
    estimated_hours: Mapped[float] = mapped_column(Float, default=1.0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped[StudyPlan] = relationship(back_populates="tasks")
