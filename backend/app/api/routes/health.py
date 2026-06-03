from fastapi import APIRouter

from app.clients.lightrag_client import LightRAGClient
from app.core.config import get_settings
from app.schemas.api import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    lightrag = await LightRAGClient().health()
    return HealthResponse(
        status="ok",
        services={
            "database": {"configured": bool(settings.database_url)},
            "redis": {"configured": bool(settings.redis_url)},
            "letta": {"base_url": settings.letta_base_url},
            "lightrag": lightrag,
            "neo4j": {"uri": settings.neo4j_uri},
            "qdrant": {"url": settings.qdrant_url},
        },
    )
