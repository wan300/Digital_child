from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.db.session import get_session
from app.models.entities import EvalRun
from app.schemas.api import EvalRunRequest, EvalRunResponse
from app.services.eval_runner import EvalRunner

router = APIRouter(prefix="/evals", tags=["evals"], dependencies=[Depends(get_current_admin)])


@router.post("/run", response_model=EvalRunResponse)
async def run_eval(payload: EvalRunRequest, session: AsyncSession = Depends(get_session)) -> EvalRun:
    return await EvalRunner().run(session, payload.persona_id)


@router.get("/runs/{run_id}", response_model=EvalRunResponse)
async def get_eval_run(run_id: str, session: AsyncSession = Depends(get_session)) -> EvalRun:
    run = await session.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评测运行不存在")
    return run
