from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MotivationQuote(Base):
    __tablename__ = "motivation_library"

    id: Mapped[int] = mapped_column(primary_key=True)
    quote: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50), default="motivation")


class WaitlistEntry(Base):
    """Premium waitlist signups captured before payments go live."""

    __tablename__ = "waitlist_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    plan_interest: Mapped[str | None] = mapped_column(String(20))  # monthly | annual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BurnoutResource(Base):
    __tablename__ = "burnout_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50), index=True)  # focus | stress | sleep | exercise | motivation | wellness
    summary: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
