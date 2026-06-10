from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Note, NoteFolder, User
from schemas.misc import NoteIn, NoteOut, VerifyNoteRequest
from services import ai_service
from utils.deps import get_current_user

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("", response_model=list[NoteOut])
async def list_notes(
    q: str | None = Query(default=None, max_length=200),
    folder_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Note).where(Note.user_id == user.id).order_by(Note.updated_at.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Note.title.ilike(like), Note.content.ilike(like)))
    if folder_id:
        stmt = stmt.where(Note.folder_id == folder_id)
    rows = (await db.execute(stmt.limit(200))).scalars().all()
    return [NoteOut.model_validate(n) for n in rows]


@router.post("", response_model=NoteOut, status_code=201)
async def create_note(payload: NoteIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    note = Note(user_id=user.id, **payload.model_dump())
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return NoteOut.model_validate(note)


async def _own_note(db: AsyncSession, user_id: int, note_id: int) -> Note:
    note = (
        await db.execute(select(Note).where(Note.id == note_id, Note.user_id == user_id))
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.get("/{note_id}", response_model=NoteOut)
async def get_note(note_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return NoteOut.model_validate(await _own_note(db, user.id, note_id))


@router.put("/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: int, payload: NoteIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    note = await _own_note(db, user.id, note_id)
    for field, value in payload.model_dump().items():
        setattr(note, field, value)
    await db.commit()
    await db.refresh(note)
    return NoteOut.model_validate(note)


@router.delete("/{note_id}", status_code=204)
async def delete_note(note_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    note = await _own_note(db, user.id, note_id)
    await db.delete(note)
    await db.commit()


@router.post("/{note_id}/suggest-tags")
async def suggest_tags(note_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    note = await _own_note(db, user.id, note_id)
    tags = await ai_service.suggest_tags(note.content)
    return {"tags": tags}


@router.post("/verify")
async def verify_note(payload: VerifyNoteRequest, _: User = Depends(get_current_user)):
    try:
        return await ai_service.verify_note(payload.content)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="Verification failed — AI service unavailable")


@router.get("/folders/all")
async def list_folders(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(NoteFolder).where(NoteFolder.user_id == user.id).order_by(NoteFolder.name))
    ).scalars().all()
    return [{"id": f.id, "name": f.name} for f in rows]


@router.post("/folders", status_code=201)
async def create_folder(
    name: str = Query(min_length=1, max_length=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = NoteFolder(user_id=user.id, name=name)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return {"id": folder.id, "name": folder.name}
