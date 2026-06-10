from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    letter: str
    text: str


class OptionReview(OptionOut):
    is_correct: bool
    explanation: str | None
    pct_chosen: float = 0.0


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    qid: int | None
    subject: str
    topic: str
    difficulty: str
    question_text: str
    options: list[OptionOut]
    bookmarked: bool = False
    flagged: bool = False


class QuestionReview(BaseModel):
    id: int
    qid: int | None
    subject: str
    topic: str
    difficulty: str
    question_text: str
    options: list[OptionReview]
    explanation: str
    learning_point: str | None
    reference_source: str | None
    updated_at: datetime
    correct_letter: str
    selected_letter: str
    is_correct: bool
    time_taken_seconds: int


class AttemptIn(BaseModel):
    selected_letter: str = Field(pattern="^[A-E]$")
    time_taken_seconds: int = Field(default=0, ge=0)


class QuestionCreate(BaseModel):
    subject: str
    topic: str
    difficulty: str = Field(pattern="^(easy|medium|hard)$")
    question_text: str
    explanation: str
    learning_point: str | None = None
    reference_source: str | None = None
    options: list[dict]  # {letter, text, is_correct, explanation?}


class GenerateMCQRequest(BaseModel):
    subject: str
    topic: str
    difficulty: str = Field(pattern="^(easy|medium|hard)$")
    count: int = Field(default=5, ge=1, le=20)


class QuestionListItem(BaseModel):
    id: int
    qid: int | None
    subject: str
    topic: str
    difficulty: str
    attempted: bool
    last_correct: bool | None
    bookmarked: bool
