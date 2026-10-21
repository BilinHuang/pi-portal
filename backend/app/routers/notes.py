"""Node Announcements & Scratchpad Notes Router."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import CurrentIdentity, can_launch_service, get_current_identity
from ..models import Note, Service

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _require_notes_available(
    identity: CurrentIdentity = Depends(get_current_identity),
    db: Session = Depends(get_db),
) -> CurrentIdentity:
    """Ensure the caller has permission and 'pi-status-note' is active."""
    service = db.query(Service).filter(Service.slug == "pi-status-note").first()
    if service and not can_launch_service(identity, service):
        raise HTTPException(status_code=404, detail="Not Found")
    return identity


class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=10000)
    category: str = Field(default="memo", pattern=r"^(bulletin|memo|todo|code)$")
    priority: str = Field(default="normal", pattern=r"^(normal|warning|info|success)$")
    is_pinned: bool = False


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    content: Optional[str] = Field(default=None, min_length=1, max_length=10000)
    category: Optional[str] = Field(
        default=None, pattern=r"^(bulletin|memo|todo|code)$"
    )
    priority: Optional[str] = Field(
        default=None, pattern=r"^(normal|warning|info|success)$"
    )
    is_pinned: Optional[bool] = None


def _serialize_note(n: Note) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "category": n.category,
        "priority": n.priority,
        "is_pinned": bool(n.is_pinned),
        "author": n.author,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


@router.get("")
def list_notes(
    category: Optional[str] = None,
    q: Optional[str] = None,
    identity: CurrentIdentity = Depends(_require_notes_available),
    db: Session = Depends(get_db),
):
    """List notes ordered by pinned status first, then most recently updated."""
    query = db.query(Note)
    if category and category != "all":
        query = query.filter(Note.category == category)
    if q and q.strip():
        kw = f"%{q.strip()}%"
        query = query.filter((Note.title.ilike(kw)) | (Note.content.ilike(kw)))

    items = query.order_by(
        Note.is_pinned.desc(), Note.updated_at.desc(), Note.id.desc()
    ).all()
    return [_serialize_note(n) for n in items]


@router.post("")
def create_note(
    payload: NoteCreate,
    identity: CurrentIdentity = Depends(_require_notes_available),
    db: Session = Depends(get_db),
):
    """Create a new announcement or note."""
    author_name = identity.user.username if identity.user else "访客 (Guest)"
    now = datetime.now(timezone.utc)
    note = Note(
        title=payload.title.strip(),
        content=payload.content.strip(),
        category=payload.category,
        priority=payload.priority,
        is_pinned=payload.is_pinned,
        author=author_name,
        created_at=now,
        updated_at=now,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _serialize_note(note)


@router.put("/{note_id}")
def update_note(
    note_id: int,
    payload: NoteUpdate,
    identity: CurrentIdentity = Depends(_require_notes_available),
    db: Session = Depends(get_db),
):
    """Update an existing note."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Not Found")

    if payload.title is not None:
        note.title = payload.title.strip()
    if payload.content is not None:
        note.content = payload.content.strip()
    if payload.category is not None:
        note.category = payload.category
    if payload.priority is not None:
        note.priority = payload.priority
    if payload.is_pinned is not None:
        note.is_pinned = payload.is_pinned

    note.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(note)
    return _serialize_note(note)


@router.patch("/{note_id}/pin")
def toggle_pin_note(
    note_id: int,
    identity: CurrentIdentity = Depends(_require_notes_available),
    db: Session = Depends(get_db),
):
    """Toggle pinned status for a note."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Not Found")
    note.is_pinned = not note.is_pinned
    note.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True, "is_pinned": bool(note.is_pinned)}


@router.delete("/{note_id}")
def delete_note(
    note_id: int,
    identity: CurrentIdentity = Depends(_require_notes_available),
    db: Session = Depends(get_db),
):
    """Delete a note by ID."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Not Found")
    db.delete(note)
    db.commit()
    return {"success": True}
