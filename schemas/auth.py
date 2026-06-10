from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    country: str | None = None
    graduation_year: int | None = Field(default=None, ge=1950, le=2030)
    working_status: str | None = None
    amc_attempts: int = Field(default=0, ge=0, le=20)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    country: str | None
    graduation_year: int | None
    working_status: str | None
    amc_attempts: int
    subscription_status: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    is_admin: bool = False
    onboarding_complete: bool = False


class PreferencesIn(BaseModel):
    exam_date: date
    daily_hours: float = Field(ge=0.5, le=16)
    strong_subjects: list[str] = []
    weak_subjects: list[str] = []
    learning_style: str | None = None


class PreferencesOut(PreferencesIn):
    model_config = ConfigDict(from_attributes=True)

    onboarding_complete: bool
