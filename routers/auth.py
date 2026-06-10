from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import AdminUser, User, UserPreferences
from schemas.auth import LoginRequest, PreferencesIn, PreferencesOut, RegisterRequest, TokenResponse, UserOut
from utils.deps import get_current_user
from utils.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def _is_admin(db: AsyncSession, user_id: int) -> bool:
    result = await db.execute(select(AdminUser).where(AdminUser.user_id == user_id))
    return result.scalar_one_or_none() is not None


async def _onboarding_complete(db: AsyncSession, user_id: int) -> bool:
    result = await db.execute(select(UserPreferences).where(UserPreferences.user_id == user_id))
    prefs = result.scalar_one_or_none()
    return bool(prefs and prefs.onboarding_complete)


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        country=payload.country,
        graduation_year=payload.graduation_year,
        working_status=payload.working_status,
        amc_attempts=payload.amc_attempts,
        last_login=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.email, is_admin=False)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    is_admin = await _is_admin(db, user.id)
    token = create_access_token(user.id, user.email, is_admin=is_admin)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        is_admin=is_admin,
        onboarding_complete=await _onboarding_complete(db, user.id),
    )


@router.get("/me", response_model=TokenResponse)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    is_admin = await _is_admin(db, user.id)
    token = create_access_token(user.id, user.email, is_admin=is_admin)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        is_admin=is_admin,
        onboarding_complete=await _onboarding_complete(db, user.id),
    )


@router.get("/preferences", response_model=PreferencesOut | None)
async def get_preferences(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserPreferences).where(UserPreferences.user_id == user.id))
    prefs = result.scalar_one_or_none()
    return PreferencesOut.model_validate(prefs) if prefs else None


@router.put("/preferences", response_model=PreferencesOut)
async def save_preferences(
    payload: PreferencesIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserPreferences).where(UserPreferences.user_id == user.id))
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = UserPreferences(user_id=user.id)
        db.add(prefs)
    prefs.exam_date = payload.exam_date
    prefs.daily_hours = payload.daily_hours
    prefs.strong_subjects = payload.strong_subjects
    prefs.weak_subjects = payload.weak_subjects
    prefs.learning_style = payload.learning_style
    prefs.onboarding_complete = True
    await db.commit()
    await db.refresh(prefs)
    return PreferencesOut.model_validate(prefs)
