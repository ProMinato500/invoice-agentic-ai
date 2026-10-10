import hashlib
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import settings
from backend.app.extraction import inspect_pdf
from backend.app.models import Document, uid


def store_pdf(db, content, name, kind, org):
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "PDF exceeds the configured size limit")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(415, "A real PDF signature is required")
    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(
        select(Document).where(
            Document.organization_id == org,
            Document.sha256 == digest,
            Document.kind == kind,
        )
    )
    if existing:
        return existing, True
    docid = uid()
    folder = settings.storage / "documents" / org
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{docid}.pdf"
    path.write_bytes(content)
    try:
        count = inspect_pdf(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    document = Document(
        id=docid,
        organization_id=org,
        name=Path(name.replace("\\", "/")).name[:255],
        kind=kind,
        sha256=digest,
        path=str(path),
        page_count=count,
        size=len(content),
    )
    db.add(document)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        path.unlink(missing_ok=True)
        existing = db.scalar(
            select(Document).where(
                Document.organization_id == org,
                Document.sha256 == digest,
                Document.kind == kind,
            )
        )
        if not existing:
            raise
        return existing, True
    return document, False
