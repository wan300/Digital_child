from fastapi import APIRouter

from app.api.routes import (
    auth,
    child_observations,
    conversations,
    documents,
    evals,
    health,
    memory,
    personas,
    review,
    simulation,
    tools,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(personas.router)
api_router.include_router(conversations.router)
api_router.include_router(memory.router)
api_router.include_router(documents.router)
api_router.include_router(review.router)
api_router.include_router(evals.router)
api_router.include_router(tools.router)
api_router.include_router(simulation.router)
api_router.include_router(child_observations.router)
