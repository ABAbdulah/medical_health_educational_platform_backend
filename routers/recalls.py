from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import RecallDocument, RecallTopic, User
from utils.deps import get_current_user

router = APIRouter(prefix="/api/recalls", tags=["recalls"])

PERIODS = {"1m": 1, "3m": 3, "6m": 6, "1y": 12}


def _months_back(n: int) -> str:
    d = date.today() - timedelta(days=30 * n)
    return d.strftime("%Y-%m")


@router.get("/analytics")
async def recall_analytics(
    period: str = Query(default="6m", pattern="^(1m|3m|6m|1y)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cutoff = _months_back(PERIODS[period])

    base = (
        select(
            RecallTopic.topic,
            RecallTopic.subject,
            RecallDocument.exam_month,
            func.sum(RecallTopic.frequency).label("freq"),
        )
        .join(RecallDocument, RecallDocument.id == RecallTopic.document_id)
        .where(RecallDocument.exam_month >= cutoff, RecallDocument.status.in_(("processed", "approved")))
        .group_by(RecallTopic.topic, RecallTopic.subject, RecallDocument.exam_month)
    )
    rows = (await db.execute(base)).all()

    # heatmap: subject x month
    heatmap: dict[tuple[str, str], int] = {}
    topic_totals: dict[str, dict] = {}
    for topic, subject, month, freq in rows:
        heatmap[(subject, month)] = heatmap.get((subject, month), 0) + int(freq)
        entry = topic_totals.setdefault(
            topic, {"topic": topic, "subject": subject, "frequency": 0, "months": {}}
        )
        entry["frequency"] += int(freq)
        entry["months"][month] = entry["months"].get(month, 0) + int(freq)

    # trend: compare most recent month vs previous for each topic
    table = []
    for entry in topic_totals.values():
        months = sorted(entry["months"].keys())
        trend = "stable"
        if len(months) >= 2:
            last, prev = entry["months"][months[-1]], entry["months"][months[-2]]
            trend = "up" if last > prev else "down" if last < prev else "stable"
        table.append(
            {
                "topic": entry["topic"], "subject": entry["subject"],
                "frequency": entry["frequency"], "trend": trend,
                "last_seen": months[-1] if months else None,
            }
        )
    table.sort(key=lambda t: -t["frequency"])

    months_axis = sorted({m for (_, m) in heatmap.keys()})
    subjects_axis = sorted({s for (s, _) in heatmap.keys()})

    return {
        "heatmap": {
            "months": months_axis,
            "subjects": subjects_axis,
            "cells": [
                {"subject": s, "month": m, "frequency": f} for (s, m), f in heatmap.items()
            ],
        },
        "top_topics": table[:20],
        "table": table[:100],
        "trend_series": [
            {
                "topic": t["topic"],
                "points": [
                    {"month": m, "frequency": topic_totals[t["topic"]]["months"].get(m, 0)}
                    for m in months_axis
                ],
            }
            for t in table[:5]
        ],
    }
