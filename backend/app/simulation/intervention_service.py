from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditLog, SimulationWorld, UserIntervention
from app.schemas.api import UserInterventionCreate


class InterventionService:
    allowed_child_interventions = {"environment_event", "adult_behavior", "npc_behavior", "rule_change", "gm_event"}
    forbidden_child_payload_keys = {"needs", "development", "state_changes", "direct_state_changes", "development_delta", "traits"}

    async def create(
        self,
        session: AsyncSession,
        *,
        world: SimulationWorld,
        payload: UserInterventionCreate,
        admin_actor: str,
    ) -> UserIntervention:
        self._validate_child_intervention(world, payload)
        actor = payload.actor or admin_actor
        intervention = UserIntervention(
            world_id=world.id,
            actor=actor,
            intervention_type=payload.intervention_type,
            payload=payload.payload,
            status="pending",
        )
        session.add(intervention)
        await session.flush()
        session.add(
            AuditLog(
                actor=admin_actor,
                action="simulation.intervention.create",
                target_type="simulation_world",
                target_id=world.id,
                payload={
                    "intervention_id": intervention.id,
                    "intervention_type": intervention.intervention_type,
                    "actor": actor,
                    "payload": intervention.payload,
                },
            )
        )
        return intervention

    def _validate_child_intervention(self, world: SimulationWorld, payload: UserInterventionCreate) -> None:
        if (world.settings or {}).get("world_type") != "child_growth_v1":
            return
        if payload.intervention_type not in self.allowed_child_interventions:
            raise ValueError("儿童世界运行中只能注入环境、规则、成人行为或 NPC 行为事件。")
        keys = set(payload.payload or {})
        if keys & self.forbidden_child_payload_keys:
            raise ValueError("儿童世界普通观察流程不能直接编辑 needs、development、traits 或完整状态。")
