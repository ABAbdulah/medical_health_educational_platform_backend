import csv
import io
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import get_db
from models import (
    BurnoutResource, MotivationQuote, Question, QuestionOption,
    RecallDocument, RecallTopic, User,
)
from schemas.question import GenerateMCQRequest, QuestionCreate
from services import ai_service
from utils.deps import get_current_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(get_current_admin)])


async def _next_qid(db: AsyncSession) -> int:
    return ((await db.execute(select(func.max(Question.qid)))).scalar() or 0) + 1


@router.get("/stats")
async def admin_stats(db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    premium = (
        await db.execute(
            select(func.count(User.id)).where(User.subscription_status.in_(("monthly", "annual")))
        )
    ).scalar() or 0
    questions = (await db.execute(select(func.count(Question.id)))).scalar() or 0
    recall_docs = (await db.execute(select(func.count(RecallDocument.id)))).scalar() or 0
    return {"users": users, "premium_subscriptions": premium, "mcq_count": questions, "recall_docs": recall_docs}


@router.get("/users")
async def list_users(q: str | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(User).order_by(User.created_at.desc()).limit(200)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.email.ilike(like)) | (User.full_name.ilike(like)))
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": u.id, "email": u.email, "full_name": u.full_name, "country": u.country,
            "subscription_status": u.subscription_status,
            "created_at": u.created_at.isoformat(),
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in rows
    ]


class ChangeSubscription(BaseModel):
    subscription_status: str = Field(pattern="^(free|monthly|annual)$")


@router.patch("/users/{user_id}/subscription")
async def change_subscription(user_id: int, payload: ChangeSubscription, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.subscription_status = payload.subscription_status
    await db.commit()
    return {"id": user.id, "subscription_status": user.subscription_status}


# ---------- MCQ management ----------

def _question_admin_dict(q: Question) -> dict:
    return {
        "id": q.id, "qid": q.qid, "subject": q.subject, "topic": q.topic,
        "difficulty": q.difficulty, "status": q.status,
        "question_text": q.question_text, "explanation": q.explanation,
        "learning_point": q.learning_point, "reference_source": q.reference_source,
        "updated_at": q.updated_at.isoformat(),
        "options": [
            {"letter": o.letter, "text": o.text, "is_correct": o.is_correct, "explanation": o.explanation}
            for o in q.options
        ],
    }


@router.get("/questions")
async def list_questions_admin(
    subject: str | None = None,
    difficulty: str | None = None,
    status: str | None = None,  # published | draft | archived | None=all
    page: int = 1,
    page_size: int = 25,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Question).options(selectinload(Question.options))
    if subject and subject != "All":
        stmt = stmt.where(Question.subject == subject)
    if difficulty and difficulty != "All":
        stmt = stmt.where(Question.difficulty == difficulty.lower())
    if status and status != "All":
        stmt = stmt.where(Question.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(
            stmt.order_by(Question.qid).offset((max(page, 1) - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [_question_admin_dict(q) for q in rows],
    }


@router.put("/questions/{question_id}")
async def update_question(question_id: int, payload: QuestionCreate, db: AsyncSession = Depends(get_db)):
    q = (
        await db.execute(
            select(Question).options(selectinload(Question.options)).where(Question.id == question_id)
        )
    ).scalar_one_or_none()
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    q.subject = payload.subject
    q.topic = payload.topic
    q.difficulty = payload.difficulty
    q.question_text = payload.question_text
    q.explanation = payload.explanation
    q.learning_point = payload.learning_point
    q.reference_source = payload.reference_source
    # replace options wholesale (delete-orphan cascade cleans up the old rows)
    q.options.clear()
    for opt in payload.options:
        q.options.append(
            QuestionOption(
                letter=opt["letter"], text=opt["text"],
                is_correct=bool(opt.get("is_correct")), explanation=opt.get("explanation"),
            )
        )
    await db.commit()
    await db.refresh(q, attribute_names=["options"])
    return _question_admin_dict(q)


@router.post("/questions", status_code=201)
async def create_question(payload: QuestionCreate, db: AsyncSession = Depends(get_db)):
    q = Question(
        qid=await _next_qid(db),
        subject=payload.subject, topic=payload.topic, difficulty=payload.difficulty,
        question_text=payload.question_text, explanation=payload.explanation,
        learning_point=payload.learning_point, reference_source=payload.reference_source,
    )
    db.add(q)
    await db.flush()
    for opt in payload.options:
        db.add(
            QuestionOption(
                question_id=q.id, letter=opt["letter"], text=opt["text"],
                is_correct=bool(opt.get("is_correct")), explanation=opt.get("explanation"),
            )
        )
    await db.commit()
    return {"id": q.id, "qid": q.qid}


@router.delete("/questions/{question_id}", status_code=204)
async def delete_question(question_id: int, db: AsyncSession = Depends(get_db)):
    q = await db.get(Question, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    await db.delete(q)
    await db.commit()


@router.post("/generate-mcqs")
async def generate_mcqs(payload: GenerateMCQRequest, db: AsyncSession = Depends(get_db)):
    """AI MCQ generator: Ollama locally, claude-haiku on Railway."""
    try:
        mcqs = await ai_service.generate_mcqs(payload.subject, payload.topic, payload.difficulty, payload.count)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MCQ generation failed: {exc}")

    created = []
    for mcq in mcqs:
        try:
            q = Question(
                qid=await _next_qid(db),
                subject=payload.subject, topic=payload.topic,
                difficulty=mcq.get("difficulty", payload.difficulty),
                question_text=mcq["question_text"], explanation=mcq.get("explanation", ""),
                learning_point=mcq.get("learning_point"),
                reference_source=mcq.get("reference"),
                status="draft",
            )
            db.add(q)
            await db.flush()
            for opt in mcq["options"]:
                db.add(
                    QuestionOption(
                        question_id=q.id, letter=opt["letter"], text=opt["text"],
                        is_correct=bool(opt.get("is_correct")),
                    )
                )
            created.append(q.id)
        except (KeyError, TypeError):
            continue  # skip malformed AI output rows
    await db.commit()
    return {"generated": len(created), "question_ids": created, "status": "draft — review before publishing"}


@router.patch("/questions/{question_id}/publish")
async def publish_question(question_id: int, db: AsyncSession = Depends(get_db)):
    q = await db.get(Question, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    q.status = "published"
    await db.commit()
    return {"id": q.id, "status": q.status}


@router.get("/questions/drafts")
async def list_drafts(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Question).options(selectinload(Question.options))
            .where(Question.status == "draft").order_by(Question.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": q.id, "qid": q.qid, "subject": q.subject, "topic": q.topic,
            "difficulty": q.difficulty, "question_text": q.question_text,
            "options": [{"letter": o.letter, "text": o.text, "is_correct": o.is_correct} for o in q.options],
        }
        for q in rows
    ]


@router.post("/questions/import-csv")
async def import_csv(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """CSV columns: subject,topic,difficulty,question_text,explanation,learning_point,
    reference,option_a,option_b,option_c,option_d,option_e,correct_letter"""
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    imported = 0
    for row in reader:
        try:
            q = Question(
                qid=await _next_qid(db),
                subject=row["subject"], topic=row["topic"],
                difficulty=row.get("difficulty", "medium").lower(),
                question_text=row["question_text"], explanation=row.get("explanation", ""),
                learning_point=row.get("learning_point"), reference_source=row.get("reference"),
            )
            db.add(q)
            await db.flush()
            correct = row.get("correct_letter", "A").strip().upper()
            for letter in "ABCDE":
                text = row.get(f"option_{letter.lower()}")
                if text:
                    db.add(
                        QuestionOption(
                            question_id=q.id, letter=letter, text=text, is_correct=letter == correct
                        )
                    )
            imported += 1
        except KeyError:
            continue
    await db.commit()
    return {"imported": imported}


# ---------- Recall documents ----------

@router.post("/recalls/upload", status_code=201)
async def upload_recall(
    exam_month: str = Form(pattern=r"^\d{4}-\d{2}$"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    path = os.path.join(settings.UPLOAD_DIR, f"{uuid.uuid4().hex}.pdf")
    raw = await file.read()
    with open(path, "wb") as fh:
        fh.write(raw)

    doc = RecallDocument(filename=file.filename, exam_month=exam_month, file_path=path, status="processing")
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # extract text with PyMuPDF
    try:
        import fitz  # PyMuPDF

        pdf = fitz.open(path)
        text = "\n".join(page.get_text() for page in pdf)
        pdf.close()
    except Exception:
        doc.status = "failed"
        await db.commit()
        raise HTTPException(status_code=422, detail="Could not extract text from PDF")

    try:
        topics = await ai_service.extract_recall_topics(text)
    except Exception as exc:
        doc.status = "failed"
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Topic extraction failed: {exc}")

    for t in topics:
        if not isinstance(t, dict) or "topic" not in t:
            continue
        db.add(
            RecallTopic(
                document_id=doc.id, topic=str(t["topic"])[:255],
                subtopic=str(t.get("subtopic") or "")[:255] or None,
                subject=str(t.get("subject_area", "Medicine"))[:100],
                frequency=int(t.get("frequency_mentioned", 1) or 1),
            )
        )
    doc.status = "processed"
    await db.commit()
    return {"id": doc.id, "status": doc.status, "topics_extracted": len(topics)}


@router.get("/recalls")
async def list_recall_docs(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(RecallDocument).order_by(RecallDocument.upload_date.desc()))).scalars().all()
    return [
        {
            "id": d.id, "filename": d.filename, "exam_month": d.exam_month,
            "status": d.status, "upload_date": d.upload_date.isoformat(),
        }
        for d in rows
    ]


@router.get("/recalls/{doc_id}/topics")
async def list_recall_topics(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await db.get(RecallDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    rows = (
        await db.execute(
            select(RecallTopic).where(RecallTopic.document_id == doc_id)
            .order_by(RecallTopic.frequency.desc())
        )
    ).scalars().all()
    return [
        {
            "id": t.id, "topic": t.topic, "subtopic": t.subtopic,
            "subject": t.subject, "frequency": t.frequency,
        }
        for t in rows
    ]


@router.patch("/recalls/{doc_id}/approve")
async def approve_recall(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await db.get(RecallDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.status = "approved"
    await db.commit()
    return {"id": doc.id, "status": doc.status}


# ---------- Content management ----------

class QuoteIn(BaseModel):
    quote: str
    author: str
    category: str = "motivation"


@router.get("/quotes")
async def list_quotes(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(MotivationQuote).order_by(MotivationQuote.id))).scalars().all()
    return [{"id": r.id, "quote": r.quote, "author": r.author, "category": r.category} for r in rows]


@router.post("/quotes", status_code=201)
async def add_quote(payload: QuoteIn, db: AsyncSession = Depends(get_db)):
    row = MotivationQuote(**payload.model_dump())
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.delete("/quotes/{quote_id}", status_code=204)
async def delete_quote(quote_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(MotivationQuote, quote_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    await db.delete(row)
    await db.commit()


class ArticleIn(BaseModel):
    title: str
    category: str
    summary: str
    content: str


@router.post("/articles", status_code=201)
async def add_article(payload: ArticleIn, db: AsyncSession = Depends(get_db)):
    row = BurnoutResource(**payload.model_dump())
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.put("/articles/{article_id}")
async def update_article(article_id: int, payload: ArticleIn, db: AsyncSession = Depends(get_db)):
    row = await db.get(BurnoutResource, article_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")
    row.title = payload.title
    row.category = payload.category
    row.summary = payload.summary
    row.content = payload.content
    await db.commit()
    return {"id": row.id}


@router.delete("/articles/{article_id}", status_code=204)
async def delete_article(article_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(BurnoutResource, article_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")
    await db.delete(row)
    await db.commit()
