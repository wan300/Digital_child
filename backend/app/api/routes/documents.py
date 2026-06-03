from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.clients.lightrag_client import LightRAGClient
from app.db.session import get_session
from app.models.entities import Corpus, Document, Event, Persona
from app.schemas.api import CorpusCreate, CorpusResponse, DocumentResponse, DocumentSearchRequest, EvidenceItem
from app.services.context_builder import ContextBuilder

router = APIRouter(tags=["documents"], dependencies=[Depends(get_current_admin)])


@router.post("/corpora", response_model=CorpusResponse)
async def create_corpus(payload: CorpusCreate, session: AsyncSession = Depends(get_session)) -> Corpus:
    if await session.get(Persona, payload.persona_id) is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    corpus = Corpus(**payload.model_dump())
    session.add(corpus)
    await session.commit()
    await session.refresh(corpus)
    return corpus


@router.get("/corpora", response_model=list[CorpusResponse])
async def list_corpora(persona_id: str | None = None, session: AsyncSession = Depends(get_session)) -> list[Corpus]:
    stmt = select(Corpus).order_by(desc(Corpus.updated_at))
    if persona_id:
        stmt = stmt.where(Corpus.persona_id == persona_id)
    return (await session.execute(stmt)).scalars().all()


@router.post("/corpora/{corpus_id}/documents", response_model=DocumentResponse)
async def upload_document(corpus_id: str, request: Request, session: AsyncSession = Depends(get_session)) -> Document:
    corpus = await session.get(Corpus, corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="文档库不存在")

    content_type = request.headers.get("content-type", "")
    filename = "document.txt"
    raw_text = ""
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            filename = getattr(upload, "filename", None) or filename
            raw_bytes = await upload.read()
            raw_text = raw_bytes.decode("utf-8", errors="replace")
        else:
            filename = str(form.get("filename") or filename)
            raw_text = str(form.get("raw_text") or form.get("text") or "")
    else:
        data = await request.json()
        filename = data.get("filename") or filename
        raw_text = data.get("raw_text") or data.get("text") or ""
        content_type = data.get("content_type") or "text/plain"

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="文档内容不能为空")
    if not any(filename.lower().endswith(ext) for ext in (".txt", ".md", ".json", ".csv")):
        raise HTTPException(status_code=400, detail="第一版只支持 txt/md/json/csv 文本文件")

    external_id = await LightRAGClient().insert_text(text=raw_text, filename=filename, workspace=corpus.persona_id)
    document = Document(
        corpus_id=corpus.id,
        persona_id=corpus.persona_id,
        filename=filename,
        raw_text=raw_text,
        content_type=content_type.split(";")[0],
        status="indexed",
        external_id=external_id,
    )
    session.add(document)
    await session.flush()
    session.add(
        Event(
            persona_id=corpus.persona_id,
            event_type="document_import",
            source="document_upload",
            payload={"document_id": document.id, "filename": filename, "corpus_id": corpus.id},
        )
    )
    await session.commit()
    await session.refresh(document)
    return document


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str, session: AsyncSession = Depends(get_session)) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return document


@router.post("/documents/search", response_model=list[EvidenceItem])
async def search_documents(payload: DocumentSearchRequest, session: AsyncSession = Depends(get_session)) -> list[EvidenceItem]:
    persona = await session.get(Persona, payload.persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="人格不存在")
    bundle = await ContextBuilder().build(session, persona=persona, query=payload.query, counterparty_user_id=None, conversation_id=None)
    return bundle.document_evidence[: payload.k]
