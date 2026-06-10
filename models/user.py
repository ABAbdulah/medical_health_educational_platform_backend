from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str | None] = mapped_column(String(100))
    graduation_year: Mapped[int | None] = mapped_column(Integer)
    working_status: Mapped[str | None] = mapped_column(String(50))  # full_time | part_time | not_working
    amc_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    subscription_status: Mapped[str] = mapped_column(String(20), default="free")  # free | monthly | annual
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    preferences: Mapped["UserPreferences | None"] = relationship(back_populates="user", uselist=False)
    admin_profile: Mapped["AdminUser | None"] = relationship(back_populates="user", uselist=False)


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    exam_date: Mapped[date | None] = mapped_column(Date)
    daily_hours: Mapped[float | None] = mapped_column()
    strong_subjects: Mapped[list] = mapped_column(JSON, default=list)
    weak_subjects: Mapped[list] = mapped_column(JSON, default=list)
    learning_style: Mapped[str | None] = mapped_column(String(50))
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="preferences")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    role: Mapped[str] = mapped_column(String(50), default="admin")  # admin | superadmin
    permissions: Mapped[list] = mapped_column(JSON, default=list)

    user: Mapped[User] = relationship(back_populates="admin_profile")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_type: Mapped[str] = mapped_column(String(20))  # monthly | annual
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | cancelled | expired
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
