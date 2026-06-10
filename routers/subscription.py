"""Subscription module — Stripe placeholder, ready to activate with real keys."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Subscription, User
from utils.deps import get_current_user

router = APIRouter(prefix="/api/subscription", tags=["subscription"])

PLANS = [
    {
        "id": "free", "name": "Free", "price_aud": 0, "interval": None,
        "features": ["10 MCQs per day", "5 AI questions per day", "Basic study planner"],
    },
    {
        "id": "monthly", "name": "Monthly", "price_aud": 19.99, "interval": "month",
        "features": ["Unlimited MCQs", "Unlimited AI tutor", "Full recall analytics", "Note verification", "Priority support"],
    },
    {
        "id": "annual", "name": "Annual", "price_aud": 149.99, "interval": "year",
        "features": ["Everything in Monthly", "Save 37% vs monthly", "Early access to new features"],
    },
]


class CheckoutRequest(BaseModel):
    plan: str = Field(pattern="^(monthly|annual)$")


@router.get("/plans")
async def list_plans(user: User = Depends(get_current_user)):
    return {"plans": PLANS, "current": user.subscription_status}


@router.post("/checkout")
async def create_checkout(
    payload: CheckoutRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Placeholder for Stripe Checkout. With real keys, create a stripe.checkout.Session
    here and return its URL. For now we activate the plan directly (dev mode)."""
    if user.subscription_status == payload.plan:
        raise HTTPException(status_code=400, detail="You are already on this plan")

    days = 30 if payload.plan == "monthly" else 365
    db.add(
        Subscription(
            user_id=user.id, plan_type=payload.plan, start_date=date.today(),
            end_date=date.today() + timedelta(days=days), status="active",
        )
    )
    user.subscription_status = payload.plan
    await db.commit()
    return {"status": "activated", "plan": payload.plan, "checkout_url": None,
            "note": "Stripe placeholder — set STRIPE_SECRET_KEY to enable real payments"}
