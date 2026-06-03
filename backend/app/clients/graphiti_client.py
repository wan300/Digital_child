from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.clients.vendor_bootstrap import add_vendor_paths
from app.core.config import get_settings


@dataclass
class GraphFact:
    id: str | None
    fact: str
    score: float | None
    valid_at: datetime | None
    invalid_at: datetime | None
    metadata: dict[str, Any]


class GraphitiClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._graphiti = None
        self._init_attempted = False

    async def _get_graphiti(self):
        if self._init_attempted:
            return self._graphiti
        self._init_attempted = True
        if not self.settings.llm_api_key or self.settings.llm_api_key == "replace-me":
            return None
        try:
            add_vendor_paths()
            from graphiti_core import Graphiti

            self._graphiti = Graphiti(
                self.settings.neo4j_uri,
                self.settings.neo4j_user,
                self.settings.neo4j_password,
            )
        except Exception:
            self._graphiti = None
        return self._graphiti

    def group_id(self, persona_id: str, counterparty_user_id: str | None = None) -> str:
        if counterparty_user_id:
            return f"persona:{persona_id}:human:{counterparty_user_id}"
        return f"persona:{persona_id}:global"

    async def add_episode(
        self,
        *,
        name: str,
        body: str,
        source_description: str,
        reference_time: datetime,
        persona_id: str,
        counterparty_user_id: str | None,
    ) -> str | None:
        graphiti = await self._get_graphiti()
        if graphiti is None:
            return None
        try:
            from graphiti_core.nodes import EpisodeType

            result = await graphiti.add_episode(
                name=name,
                episode_body=body,
                source=EpisodeType.message,
                source_description=source_description,
                reference_time=reference_time,
                group_id=self.group_id(persona_id, counterparty_user_id),
            )
            episode = getattr(result, "episode", None)
            return getattr(episode, "uuid", None)
        except Exception:
            return None

    async def search(self, query: str, *, persona_id: str, counterparty_user_id: str | None, top_k: int = 8) -> list[GraphFact]:
        graphiti = await self._get_graphiti()
        if graphiti is None:
            return []
        group_ids = [self.group_id(persona_id), self.group_id(persona_id, counterparty_user_id)] if counterparty_user_id else [self.group_id(persona_id)]
        try:
            edges = await graphiti.search(query=query, group_ids=group_ids, num_results=top_k)
            facts: list[GraphFact] = []
            for edge in edges or []:
                facts.append(
                    GraphFact(
                        id=getattr(edge, "uuid", None),
                        fact=getattr(edge, "fact", "") or "",
                        score=getattr(edge, "score", None),
                        valid_at=getattr(edge, "valid_at", None),
                        invalid_at=getattr(edge, "invalid_at", None),
                        metadata={"episodes": getattr(edge, "episodes", [])},
                    )
                )
            return [fact for fact in facts if fact.fact]
        except Exception:
            return []
