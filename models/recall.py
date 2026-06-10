from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class RecallDocument(Base):
    __tablename__ = "recall_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    upload_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    exam_month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    file_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | processing | processed | approved | failed

    topics: Mapped[list["RecallTopic"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class RecallTopic(Base):
    __tablename__ = "recall_topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("recall_documents.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(String(255), index=True)
    subtopic: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(100), index=True)
    frequency: Mapped[int] = mapped_column(Integer, default=1)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[RecallDocument] = relationship(back_populates="topics")
    analytics: Mapped[list["RecallAnalytics"]] = relationship(back_populates="topic_ref", cascade="all, delete-orphan")


class RecallAnalytics(Base):
    __tablename__ = "recall_analytics"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("recall_topics.id", ondelete="CASCADE"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    frequency: Mapped[int] = mapped_column(Integer, default=0)
    trend_direction: Mapped[str] = mapped_column(String(10), default="stable")  # up | down | stable

    topic_ref: Mapped[RecallTopic] = relationship(back_populates="analytics")
