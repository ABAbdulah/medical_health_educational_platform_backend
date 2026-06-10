import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import (
    admin, auth, dashboard, flashcards, guidelines, motivation,
    notes, planner, progress, questions, recalls, subscription, tutor,
)

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="AMC Compass AI",
    description="AI-powered AMC exam preparation platform for International Medical Graduates",
    version="1.0.0",
)

allowed_origins = {settings.FRONTEND_URL, "http://localhost:3001", "http://127.0.0.1:3001"}
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


for router in (
    auth.router, dashboard.router, planner.router, guidelines.router, tutor.router,
    questions.router, recalls.router, notes.router, flashcards.router, admin.router,
    progress.router, subscription.router, motivation.router,
):
    app.include_router(router)
