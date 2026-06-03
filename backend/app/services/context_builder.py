from __future__ import annotations

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.graphiti_client import GraphitiClient
from app.clients.lightrag_client import LightRAGClient
from app.clients.mem0_client import Mem0Client
from app.core.config import get_settings
from app.models.entities import Conversation, Document, Event, MemoryRecord, Persona
from app.schemas.api import ContextBundle, EvidenceItem, SourceRef
from app.services.conflict_resolver import ConflictResolver
from app.services.retrieval_router import RetrievalRouter


class ContextBuilder:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.router = RetrievalRouter()
        self.conflicts = ConflictResolver()
        self.mem0 = Mem0Client()
        self.graphiti = GraphitiClient()
        self.lightrag = LightRAGClient()

    async def build(
        self,
        session: AsyncSession,
        *,
        persona: Persona,
        query: str,
        counterparty_user_id: str | None,
        conversation_id: str | None,
    ) -> ContextBundle:
        route = self.router.route(query)
        memories: list[EvidenceItem] = []
        temporal: list[EvidenceItem] = []
        documents: list[EvidenceItem] = []

        if route.use_mem0:
            memories.extend(await self._local_memories(session, persona.id, counterparty_user_id, query))
            memories.extend(await self._remote_memories(persona.id, counterparty_user_id, conversation_id, query))

        if route.use_graphiti:
            temporal.extend(await self._local_timeline(session, persona.id, counterparty_user_id, query))
            temporal.extend(await self._remote_timeline(persona.id, counterparty_user_id, query))

        if route.use_lightrag:
            documents.extend(await self._local_documents(session, persona.id, query))
            documents.extend(await self._remote_documents(query))

        memories = self._dedupe(memories)[: self.settings.max_memories_per_context]
        temporal = self._dedupe(temporal)[: self.settings.max_timeline_facts_per_context]
        documents = self._dedupe(documents)[: self.settings.max_document_chunks_per_context]
        conflict_notes = self.conflicts.resolve([*memories, *temporal, *documents])

        relationship = await self._relationship_summary(session, persona.id, counterparty_user_id)
        return ContextBundle(
            core_persona=persona.persona_block or persona.description or persona.name,
            current_human_relationship=relationship or persona.human_block or "尚未形成稳定关系摘要。",
            long_term_memories=memories,
            temporal_facts=temporal,
            document_evidence=documents,
            conflict_notes=conflict_notes,
            route=route.as_dict(),
        )

    async def _local_memories(self, session: AsyncSession, persona_id: str, counterparty_user_id: str | None, query: str) -> list[EvidenceItem]:
        subjects = [f"persona:{persona_id}"]
        if counterparty_user_id:
            subjects.append(f"human:{counterparty_user_id}")
        stmt = (
            select(MemoryRecord)
            .where(MemoryRecord.persona_id == persona_id, MemoryRecord.decision == "approved", MemoryRecord.subject.in_(subjects))
            .order_by(desc(MemoryRecord.updated_at))
            .limit(self.settings.max_memories_per_context * 2)
        )
        rows = (await session.execute(stmt)).scalars().all()
        query_lower = query.lower()
        ranked = sorted(rows, key=lambda item: 0 if query_lower and query_lower in item.content.lower() else 1)
        return [
            EvidenceItem(
                source="local_mem0_record",
                content=row.content,
                score=row.confidence,
                source_ref=SourceRef(source_type="memory", source_id=row.id, event_id=row.source_event_id, timestamp=row.updated_at, provenance=row.scope),
                metadata={"memory_type": row.memory_type, "subject": row.subject},
            )
            for row in ranked
        ]

    async def _remote_memories(self, persona_id: str, counterparty_user_id: str | None, conversation_id: str | None, query: str) -> list[EvidenceItem]:
        results = []
        scopes = [(f"persona:{persona_id}", None)]
        if counterparty_user_id:
            scopes.append((f"human:{counterparty_user_id}", conversation_id))
        for user_id, run_id in scopes:
            for item in await self.mem0.search(query, user_id=user_id, agent_id=persona_id, run_id=run_id, top_k=4):
                results.append(
                    EvidenceItem(
                        source="mem0",
                        content=item.content,
                        score=item.score,
                        source_ref=SourceRef(source_type="mem0", source_id=item.id, provenance=user_id),
                        metadata=item.metadata,
                    )
                )
        return results

    async def _local_timeline(self, session: AsyncSession, persona_id: str, counterparty_user_id: str | None, query: str) -> list[EvidenceItem]:
        stmt = select(Event).where(Event.persona_id == persona_id).order_by(desc(Event.reference_time)).limit(20)
        rows = (await session.execute(stmt)).scalars().all()
        items: list[EvidenceItem] = []
        query_lower = query.lower()
        for row in rows:
            text = str(row.payload)
            if query_lower and query_lower not in text.lower() and len(items) >= 5:
                continue
            if counterparty_user_id and row.payload.get("counterparty_user_id") not in (None, counterparty_user_id):
                continue
            items.append(
                EvidenceItem(
                    source="local_graph_event",
                    content=text[:1000],
                    score=None,
                    source_ref=SourceRef(source_type="event", source_id=row.id, event_id=row.id, timestamp=row.reference_time, provenance=row.source),
                    metadata={"event_type": row.event_type},
                )
            )
        return items

    async def _remote_timeline(self, persona_id: str, counterparty_user_id: str | None, query: str) -> list[EvidenceItem]:
        return [
            EvidenceItem(
                source="graphiti",
                content=fact.fact,
                score=fact.score,
                source_ref=SourceRef(source_type="graphiti", source_id=fact.id, timestamp=fact.valid_at, provenance="Graphiti EntityEdge.fact"),
                metadata={"valid_at": str(fact.valid_at), "invalid_at": str(fact.invalid_at), **fact.metadata},
            )
            for fact in await self.graphiti.search(query, persona_id=persona_id, counterparty_user_id=counterparty_user_id, top_k=8)
        ]

    async def _local_documents(self, session: AsyncSession, persona_id: str, query: str) -> list[EvidenceItem]:
        like_query = f"%{query[:80]}%" if query else "%"
        stmt = (
            select(Document)
            .where(Document.persona_id == persona_id, Document.status == "indexed", or_(Document.raw_text.ilike(like_query), Document.filename.ilike(like_query)))
            .order_by(desc(Document.updated_at))
            .limit(self.settings.max_document_chunks_per_context)
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [
            EvidenceItem(
                source="local_document",
                content=row.raw_text[:1200],
                score=None,
                source_ref=SourceRef(source_type="document", source_id=row.id, timestamp=row.updated_at, provenance=row.filename),
                metadata={"filename": row.filename, "content_type": row.content_type},
            )
            for row in rows
        ]

    async def _remote_documents(self, query: str) -> list[EvidenceItem]:
        return [
            EvidenceItem(
                source="lightrag",
                content=item.content[:1600],
                score=item.score,
                source_ref=SourceRef(source_type="lightrag", source_id=item.source_id, provenance="LightRAG reference"),
                metadata=item.metadata,
            )
            for item in await self.lightrag.query(query=query, mode="hybrid", top_k=self.settings.max_document_chunks_per_context)
        ]

    async def _relationship_summary(self, session: AsyncSession, persona_id: str, counterparty_user_id: str | None) -> str:
        if not counterparty_user_id:
            return ""
        stmt = (
            select(Conversation)
            .where(Conversation.persona_id == persona_id, Conversation.counterparty_user_id == counterparty_user_id)
            .order_by(desc(Conversation.updated_at))
            .limit(3)
        )
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            return ""
        return f"当前用户 `{counterparty_user_id}` 与该人格已有 {len(rows)} 段最近会话记录。"

    def _dedupe(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        seen: set[str] = set()
        result: list[EvidenceItem] = []
        for item in items:
            key = item.content.strip()[:240]
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result
