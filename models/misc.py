from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MotivationQuote(Base):
    __tablename__ = "motivation_library"

    id: Mapped[int] = mapped_column(primary_key=True)
    quote: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50), default="motivation")


class BurnoutResource(Base):
    __tablename__ = "burnout_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50), index=True)  # focus | stress | sleep | exercise | motivation | wellness
    summary: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
