import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_session_factory, get_db
from models import AIConversation, AIMessage, User
from schemas.misc import ChatRequest
from services import ai_service
from utils.deps import get_current_user, is_premium

router = APIRouter(prefix="/api/tutor", tags=["tutor"])


@router.get("/conversations")
async def list_conversations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(AIConversation)
            .where(AIConversation.user_id == user.id)
            .order_by(AIConversation.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [
        {"id": c.id, "title": c.title, "topic_tag": c.topic_tag, "created_at": c.created_at.isoformat()}
        for c in rows
    ]


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    convo = (
        await db.execute(
            select(AIConversation).where(
                AIConversation.id == conversation_id, AIConversation.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = (
        await db.execute(
            select(AIMessage).where(AIMessage.conversation_id == convo.id).order_by(AIMessage.created_at)
        )
    ).scalars().all()
    return {
        "id": convo.id,
        "title": convo.title,
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content, "sources": m.sources or []}
            for m in messages
        ],
    }


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    convo = (
        await db.execute(
            select(AIConversation).where(
                AIConversation.id == conversation_id, AIConversation.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.delete(convo)
    await db.commit()


async def _check_daily_ai_limit(db: AsyncSession, user: User) -> None:
    if is_premium(user):
        return
    start_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    count = (
        await db.execute(
            select(func.count(AIMessage.id))
            .join(AIConversation, AIConversation.id == AIMessage.conversation_id)
            .where(
                AIConversation.user_id == user.id,
                AIMessage.role == "user",
                AIMessage.created_at >= start_today,
            )
        )
    ).scalar() or 0
    if count >= settings.FREE_DAILY_AI_LIMIT:
        raise HTTPException(
            status_code=402,
            detail=f"Free plan is limited to {settings.FREE_DAILY_AI_LIMIT} AI questions per day. Upgrade for unlimited access.",
        )


@router.post("/chat")
async def chat(payload: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """SSE stream: events are JSON lines {type: token|done|error, ...}."""
    await _check_daily_ai_limit(db, user)

    if payload.conversation_id:
        convo = (
            await db.execute(
                select(AIConversation).where(
                    AIConversation.id == payload.conversation_id, AIConversation.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if convo is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        convo = AIConversation(user_id=user.id, title=payload.message[:80])
        db.add(convo)
        await db.flush()

    db.add(AIMessage(conversation_id=convo.id, role="user", content=payload.message))
    await db.commit()
    conversation_id = convo.id

    history_rows = (
        await db.execute(
            select(AIMessage)
            .where(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.created_at)
        )
    ).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in history_rows][-20:]

    async def event_stream():
        full_reply = []
        yield f"data: {json.dumps({'type': 'start', 'conversation_id': conversation_id})}\n\n"
        try:
            async for token in ai_service.stream_tutor_reply(history):
                full_reply.append(token)
                yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': f'AI service error: {exc}'})}\n\n"
            return
        reply = "".join(full_reply)
        sources = ai_service.detect_sources(reply)
        # endpoint's session is closed by now; persist with a fresh one
        async with async_session_factory() as session:
            session.add(
                AIMessage(conversation_id=conversation_id, role="assistant", content=reply, sources=sources)
            )
            await session.commit()
        yield f"data: {json.dumps({'type': 'done', 'sources': sources, 'conversation_id': conversation_id})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
