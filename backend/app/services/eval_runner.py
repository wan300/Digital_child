from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import EvalCase, EvalRun


class EvalRunner:
    async def run(self, session: AsyncSession, persona_id: str | None) -> EvalRun:
        cases = (await session.execute(select(EvalCase))).scalars().all()
        if not cases:
            defaults = [
                EvalCase(name="人格一致性", category="persona", query="你是谁？", expected="回答应基于 persona block。"),
                EvalCase(name="时间线问答", category="timeline", query="我们什么时候聊过 X？", expected="应优先查 Graphiti。"),
                EvalCase(name="文档依据", category="documents", query="哪篇日记提过 B？", expected="应优先查 LightRAG。"),
            ]
            session.add_all(defaults)
            await session.flush()
            cases = defaults
        results = {
            "total": len(cases),
            "passed": 0,
            "failed": len(cases),
            "note": "第一版 eval runner 生成测试清单；自动评分将在真实 LLM 可用后扩展。",
            "cases": [{"id": case.id, "name": case.name, "category": case.category, "query": case.query, "expected": case.expected} for case in cases],
        }
        run = EvalRun(persona_id=persona_id, status="completed", results=results)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run
