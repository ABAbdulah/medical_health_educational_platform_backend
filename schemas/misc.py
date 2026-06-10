from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class GuidelineTopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_name: str
    subject: str
    summary: str
    diagnosis: str
    management: str
    red_flags: str
    amc_pearls: str
    sources: list
    last_updated: datetime


class StudyTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject: str
    topic: str
    task_type: str
    estimated_hours: float
    completed: bool
    due_date: date


class StudyPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    generated_at: datetime
    target_exam_date: date
    completion_pct: float
    readiness_score: float
    status: str


class NoteIn(BaseModel):
    title: str = "Untitled note"
    content: str = ""
    folder_id: int | None = None
    tags: list[str] = []
    subject: str | None = None
    topic: str | None = None


class NoteOut(NoteIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class FlashcardIn(BaseModel):
    front_text: str = Field(min_length=1)
    back_text: str = Field(min_length=1)
    source_type: str = "manual"
    subject: str | None = None
    difficulty: str | None = Field(default=None, pattern="^(easy|medium|hard)$")
    personal_notes: str | None = None


class FlashcardUpdate(BaseModel):
    front_text: str | None = Field(default=None, min_length=1)
    back_text: str | None = Field(default=None, min_length=1)
    subject: str | None = None
    difficulty: str | None = Field(default=None, pattern="^(easy|medium|hard)$")
    personal_notes: str | None = None


class FlashcardOut(FlashcardIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class FlashcardReviewIn(BaseModel):
    rating: str = Field(pattern="^(easy|medium|hard)$")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: int | None = None
    # restrict THIS message's answer to specific approved sources (AI side panel chips)
    source_filter: list[str] | None = None
    # what the user is currently viewing (AI side panel context injection)
    page_context: str | None = Field(default=None, max_length=300)


class CustomTaskIn(BaseModel):
    subject: str = Field(min_length=1, max_length=100)
    topic: str = Field(min_length=1, max_length=255)
    estimated_hours: float = Field(default=1.0, ge=0.25, le=16)
    due_date: date
    task_type: str = Field(default="study", pattern="^(study|mcq_practice|revision|mock_exam)$")


class VerifyNoteRequest(BaseModel):
    content: str = Field(min_length=1)


class QuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quote: str
    author: str
    category: str


class BurnoutResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    summary: str
    content: str
