from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Flashcard(Base):
    __tablename__ = "flashcards"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    front_text: Mapped[str] = mapped_column(Text)
    back_text: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(30), default="manual")  # manual | mcq | topic | note | ai
    subject: Mapped[str | None] = mapped_column(String(100))
    difficulty: Mapped[str | None] = mapped_column(String(20))  # easy | medium | hard
    personal_notes: Mapped[str | None] = mapped_column(Text)  # the user's own memory tips per card
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    progress: Mapped["FlashcardProgress | None"] = relationship(
        back_populates="flashcard", uselist=False, cascade="all, delete-orphan"
    )


class FlashcardProgress(Base):
    __tablename__ = "flashcard_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    flashcard_id: Mapped[int] = mapped_column(ForeignKey("flashcards.id", ondelete="CASCADE"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    next_review_date: Mapped[date] = mapped_column(Date, index=True)
    last_reviewed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    flashcard: Mapped[Flashcard] = relationship(back_populates="progress")
