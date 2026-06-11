from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.entities import (
    AgentRelationship,
    AgentState,
    AuditLog,
    ChildWorldDraft,
    CommunityRule,
    Event,
    GrowthReport,
    MemoryRecord,
    Persona,
    RandomEventTemplate,
    SimAgent,
    SimulationAction,
    SimulationEvent,
    SimulationWorld,
    UserIntervention,
    WorldLocation,
    WorldSnapshot,
)
from app.schemas.api import (
    BranchPreviewResponse,
    ChildWorldDraftConfirm,
    ChildWorldDraftRequest,
    SimulationEventResponse,
    SimulationStepResponse,
    SimulationWorldResponse,
)
from app.simulation.concordia_adapter import ConcordiaAdapter
from app.simulation.memory_writer import SimulationMemoryWriter
from app.simulation.random_events import RandomEventScheduler
from app.simulation.rulebook import Rulebook
from app.simulation.state_projection import StateProjector

WORLD_TYPE = "child_growth_v1"
HALF_DAY_MINUTES = 720

NEED_KEYS = ("energy", "satiety", "sleep_quality", "health", "hygiene", "safety", "stress")
DEVELOPMENT_DOMAINS = {
    "language_communication": "语言沟通",
    "cognitive_attention": "认知注意",
    "motor_ability": "运动能力",
    "emotional_regulation": "情绪调节",
    "social_cooperation": "社交合作",
    "self_care_habits": "自理习惯",
}
CORE_RELATIONSHIP_METRICS = ("familiarity", "warmth", "trust_security", "tension")
ROLE_EXTRA_METRICS = {
    "caregiver": ("care_consistency", "separation_comfort"),
    "teacher": ("guidance_acceptance", "classroom_comfort"),
    "peer": ("play_preference", "cooperation_fit"),
}

TEMPLATES = {
    "curious_outgoing": {"temperament": "好奇外向", "attachment": "容易寻求成人分享", "interest": "角色游戏和自然观察"},
    "sensitive_slow_to_warm": {"temperament": "敏感慢热", "attachment": "分离时需要更明确的过渡", "interest": "安静搭建和绘本"},
    "quiet_focused": {"temperament": "安静专注", "attachment": "熟悉环境中更稳定", "interest": "拼图、积木和观察细节"},
    "active_motor": {"temperament": "活泼运动", "attachment": "通过身体活动释放情绪", "interest": "跑跳、攀爬和户外游戏"},
}

RISK_KEYWORDS = (
    "真实姓名",
    "身份证",
    "护照",
    "病历",
    "诊断证明",
    "真实学校",
    "真实班级",
    "照片",
    "虐待",
    "自杀",
    "严重创伤",
    "重大疾病",
    "违法",
    "暴力伤害",
    "长期霸凌",
)


def is_child_growth_world(world: SimulationWorld) -> bool:
    return (world.settings or {}).get("world_type") == WORLD_TYPE


def default_needs() -> dict[str, int]:
    return {
        "energy": 72,
        "satiety": 68,
        "sleep_quality": 75,
        "health": 88,
        "hygiene": 72,
        "safety": 76,
        "stress": 24,
    }


def default_development(age_months: int) -> dict[str, dict[str, Any]]:
    base = 48 + min(12, max(0, age_months - 36) // 3)
    return {
        key: {"score": clamp(base + offset, 0, 100), "trend": "stable", "evidence_buffer": [], "confidence": 0.55}
        for key, offset in {
            "language_communication": 2,
            "cognitive_attention": 1,
            "motor_ability": 0,
            "emotional_regulation": -1,
            "social_cooperation": 0,
            "self_care_habits": -2,
        }.items()
    }


def clamp(value: float | int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))


def clamp_delta(value: float, low: int, high: int) -> int:
    return max(low, min(high, int(round(value))))


def safe_memory_text(value: Any) -> str:
    text = str(value or "").strip()
    return text[:240] if text else "一次间接环境事件"


class ChildSafetyPolicy:
    def risk_flags(self, *parts: str) -> list[dict[str, str]]:
        text = "\n".join(part for part in parts if part).lower()
        flags: list[dict[str, str]] = []
        for keyword in RISK_KEYWORDS:
            if keyword.lower() in text:
                flags.append({"keyword": keyword, "severity": "high" if keyword in {"身份证", "护照", "病历", "照片"} else "review"})
        if re.search(r"\b\d{15,18}\b", text):
            flags.append({"keyword": "identity_number_pattern", "severity": "high"})
        return flags

    def assert_safe_to_confirm(self, flags: list[Any]) -> None:
        if any(isinstance(flag, dict) and flag.get("severity") == "high" for flag in flags):
            raise ValueError("草稿包含真实儿童或高风险可识别信息，不能确认创建。")

    def sanitize_event_text(self, text: str) -> tuple[str, list[dict[str, str]]]:
        flags = self.risk_flags(text)
        if flags:
            return "出现了一个需要成人温和处理的日常小插曲，系统已避免生成高风险细节。", flags
        return text, []


class ChildWorldDraftService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.safety = ChildSafetyPolicy()

    async def create_draft(self, session: AsyncSession, payload: ChildWorldDraftRequest) -> ChildWorldDraft:
        draft_data, raw_response = await self._generate(payload)
        risk_flags = self.safety.risk_flags(payload.natural_language_prompt, raw_response, json.dumps(draft_data, ensure_ascii=False))
        draft = ChildWorldDraft(
            status="draft",
            template_key=payload.template_key,
            input_params=payload.model_dump(),
            natural_language_prompt=payload.natural_language_prompt,
            raw_response=raw_response,
            parsed_draft=draft_data,
            risk_flags=risk_flags,
        )
        session.add(draft)
        await session.flush()
        return draft

    async def confirm_draft(
        self,
        session: AsyncSession,
        *,
        draft: ChildWorldDraft,
        payload: ChildWorldDraftConfirm,
        admin_actor: str,
    ) -> SimulationWorld:
        if draft.created_world_id:
            existing = await session.get(SimulationWorld, draft.created_world_id)
            if existing is not None:
                return existing
        self.safety.assert_safe_to_confirm(draft.risk_flags)
        parsed = payload.parsed_draft or draft.parsed_draft
        self._validate_draft(parsed)

        world = SimulationWorld(
            name=payload.world_name or parsed["world"].get("name") or f"{parsed['child']['name']}的成长世界",
            status="running" if payload.start_running else "paused",
            clock_time=datetime.now().astimezone(),
            speed=1.0,
            seed=payload.seed or parsed["world"].get("seed") or draft.input_params.get("seed") or 1,
            settings={
                "world_type": WORLD_TYPE,
                "growth_step_minutes": HALF_DAY_MINUTES,
                "branching": {"enabled": False, "preview_endpoint": "/api/worlds/{world_id}/branches/preview"},
            },
        )
        session.add(world)
        await session.flush()

        locations = await self._create_locations(session, world, parsed["locations"])
        child_agent = await self._create_child(session, world, locations, parsed["child"])
        npc_agents = await self._create_npcs(session, world, locations, parsed["npcs"])
        world.settings = {**world.settings, "child_agent_id": child_agent.id, "npc_agent_ids": [agent.id for agent in npc_agents]}
        await self._create_relationships(session, world, child_agent, npc_agents, parsed["relationships"])
        self._create_rules(session, world)
        self._create_random_event_templates(session, world)
        await self._persist_initial_memories(session, child_agent, parsed["child"].get("initial_memories") or [])

        init_event = SimulationEvent(
            world_id=world.id,
            tick_no=0,
            event_type="child_world_initialized",
            source="child_draft",
            status="completed",
            reference_time=world.clock_time,
            actors=[child_agent.id, *[agent.id for agent in npc_agents]],
            location_id=child_agent.current_location_id,
            payload={
                "world_id": world.id,
                "summary": "儿童成长世界已通过审核创建。",
                "observed_facts": ["创建了 1 名虚构儿童、照护者、老师、同伴和三类固定场景。"],
                "child_interpretation": "我来到一个有家、幼儿园和户外地方的小世界。",
                "gm_interpretation": "初始化事件仅建立基线，不代表成长变化。",
                "state_update_evidence": [],
                "half_day_summary": "成长模拟准备就绪。",
                "risk_flags": draft.risk_flags,
            },
        )
        session.add(init_event)
        draft.status = "confirmed"
        draft.created_world_id = world.id
        session.add(
            AuditLog(
                actor=admin_actor,
                action="child_world.confirm_draft",
                target_type="simulation_world",
                target_id=world.id,
                payload={"draft_id": draft.id, "world_type": WORLD_TYPE},
            )
        )
        await session.flush()
        return world

    async def _generate(self, payload: ChildWorldDraftRequest) -> tuple[dict[str, Any], str]:
        if self.settings.llm_api_key and self.settings.llm_api_key != "replace-me":
            try:
                raw = await self._request_llm(payload)
                return self._parse_llm(raw, payload), raw
            except Exception:
                pass
        draft = self._fallback_draft(payload)
        return draft, json.dumps(draft, ensure_ascii=False)

    async def _request_llm(self, payload: ChildWorldDraftRequest) -> str:
        body = {
            "model": self.settings.chat_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Generate a fictional 3-6 year old child growth simulation draft in Simplified Chinese. "
                        "Return only valid JSON. Do not include real child names, photos, school identifiers, diagnoses, "
                        "abuse, severe injury, major illness, illegal harm, or dramatic trauma."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Template: {payload.template_key}\n"
                        f"Age months: {payload.age_months}\n"
                        f"Caregiver labels: {payload.caregiver_1_label}, {payload.caregiver_2_label}\n"
                        f"Kindergarten class: {payload.kindergarten_class}\n"
                        f"Peer count: {payload.peer_count}\n"
                        f"Optional user description: {payload.natural_language_prompt}\n\n"
                        "JSON shape: {world, child, locations, npcs, relationships}. "
                        "Child must include name, description, persona_block, traits, needs, development, initial_memories. "
                        "NPCs must include two caregivers, one teacher, and 2-4 peers."
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}", "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    def _parse_llm(self, raw: str, payload: ChildWorldDraftRequest) -> dict[str, Any]:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("LLM draft was not an object")
        fallback = self._fallback_draft(payload)
        return self._merge_draft(fallback, parsed)

    def _fallback_draft(self, payload: ChildWorldDraftRequest) -> dict[str, Any]:
        template = TEMPLATES.get(payload.template_key, TEMPLATES["curious_outgoing"])
        child_name = payload.child_name or "小雨"
        peer_count = max(2, min(4, payload.peer_count))
        peers = [
            {
                "name": name,
                "role": "peer",
                "display_label": name,
                "description": desc,
                "traits": {"role": "peer", "temperament": temperament},
                "relationship_type": "peer",
            }
            for name, desc, temperament in [
                ("安安", "喜欢搭积木的同伴。", "安静友好"),
                ("乐乐", "喜欢追逐和户外游戏的同伴。", "活泼直接"),
                ("米米", "喜欢绘本和角色扮演的同伴。", "想象力丰富"),
                ("辰辰", "偶尔坚持己见但愿意合作的同伴。", "独立"),
            ][:peer_count]
        ]
        return {
            "world": {"name": f"{child_name}的半天成长观察", "seed": payload.seed or 7},
            "child": {
                "name": child_name,
                "description": f"{payload.age_months} 个月的虚构儿童，气质基线为{template['temperament']}。",
                "persona_block": (
                    f"{child_name}是 3-6 岁范围内的虚构儿童，年龄 {payload.age_months} 个月。"
                    f"家庭结构使用 caregiver_1/caregiver_2，称谓为 {payload.caregiver_1_label}/{payload.caregiver_2_label}。"
                    f"幼儿园班级为{payload.kindergarten_class}。气质基线：{template['temperament']}；"
                    f"依恋倾向：{template['attachment']}；初始兴趣：{template['interest']}。"
                    "系统只模拟温和、可恢复的日常经历，不输出诊断或现实育儿建议。"
                ),
                "human_block": "用户是观察者，只能通过环境、成人行为、NPC 行为和规则间接影响成长。",
                "traits": {
                    "role": "child",
                    "age_months": payload.age_months,
                    "family_structure": {
                        "caregiver_1": {"display_label": payload.caregiver_1_label},
                        "caregiver_2": {"display_label": payload.caregiver_2_label},
                    },
                    "kindergarten_class": payload.kindergarten_class,
                    "temperament_baseline": template["temperament"],
                    "attachment_tendency": template["attachment"],
                    "initial_interests": [template["interest"]],
                    "sensitive_points": ["陌生转换", "疲劳时被催促"],
                },
                "needs": default_needs(),
                "development": default_development(payload.age_months),
                "initial_memories": [
                    f"{child_name}通常在熟悉成人回应后更愿意尝试新活动。",
                    f"{child_name}对{template['interest']}表现出稳定兴趣。",
                ],
            },
            "locations": [
                {"name": "家庭", "kind": "home", "x": 18, "y": 52, "description": "起床准备、用餐、亲子互动、自由玩耍、洗漱整理和睡前入睡。"},
                {"name": "幼儿园", "kind": "kindergarten", "x": 52, "y": 28, "description": "入园分离、集体活动、自由游戏、餐点午休和户外活动。"},
                {"name": "社区/户外", "kind": "community", "x": 78, "y": 68, "description": "散步探索、游乐设施、自然观察、邻里互动和温和突发小事件。"},
            ],
            "npcs": [
                {
                    "name": payload.caregiver_1_label,
                    "role": "caregiver",
                    "display_label": payload.caregiver_1_label,
                    "description": f"{payload.caregiver_1_label}，提供稳定日常陪伴。",
                    "traits": {"role": "caregiver", "care_style": "稳定回应"},
                    "relationship_type": "caregiver",
                },
                {
                    "name": payload.caregiver_2_label,
                    "role": "caregiver",
                    "display_label": payload.caregiver_2_label,
                    "description": f"{payload.caregiver_2_label}，参与陪伴和生活规则。",
                    "traits": {"role": "caregiver", "care_style": "温和边界"},
                    "relationship_type": "caregiver",
                },
                {
                    "name": "林老师",
                    "role": "teacher",
                    "display_label": "林老师",
                    "description": "幼儿园老师，负责活动引导和冲突修复。",
                    "traits": {"role": "teacher", "guidance_style": "清晰温和"},
                    "relationship_type": "teacher",
                },
                *peers,
            ],
            "relationships": [],
        }

    def _merge_draft(self, fallback: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
        merged = {**fallback, **parsed}
        merged["child"] = {**fallback["child"], **(parsed.get("child") if isinstance(parsed.get("child"), dict) else {})}
        merged["locations"] = parsed.get("locations") if isinstance(parsed.get("locations"), list) and parsed.get("locations") else fallback["locations"]
        merged["npcs"] = parsed.get("npcs") if isinstance(parsed.get("npcs"), list) and parsed.get("npcs") else fallback["npcs"]
        merged["relationships"] = parsed.get("relationships") if isinstance(parsed.get("relationships"), list) else []
        return merged

    def _validate_draft(self, draft: dict[str, Any]) -> None:
        if not isinstance(draft, dict) or not isinstance(draft.get("child"), dict):
            raise ValueError("儿童世界草稿缺少 child。")
        child = draft["child"]
        age = int(child.get("traits", {}).get("age_months") or 48)
        if age < 36 or age > 72:
            raise ValueError("儿童年龄必须在 36-72 个月。")
        npcs = draft.get("npcs") if isinstance(draft.get("npcs"), list) else []
        if len([npc for npc in npcs if npc.get("role") == "caregiver"]) < 2:
            raise ValueError("儿童世界至少需要 2 名照护者。")
        if len([npc for npc in npcs if npc.get("role") == "teacher"]) < 1:
            raise ValueError("儿童世界至少需要 1 名老师。")
        if len([npc for npc in npcs if npc.get("role") == "peer"]) < 2:
            raise ValueError("儿童世界至少需要 2 名同伴。")
        kinds = {item.get("kind") for item in draft.get("locations", []) if isinstance(item, dict)}
        if {"home", "kindergarten", "community"} - kinds:
            raise ValueError("儿童世界必须包含家庭、幼儿园、社区/户外三类场景。")

    async def _create_locations(self, session: AsyncSession, world: SimulationWorld, rows: list[dict[str, Any]]) -> dict[str, WorldLocation]:
        locations: dict[str, WorldLocation] = {}
        for row in rows:
            location = WorldLocation(
                world_id=world.id,
                name=str(row.get("name") or row.get("kind")),
                kind=str(row.get("kind") or "place"),
                x=float(row.get("x") or 0),
                y=float(row.get("y") or 0),
                description=str(row.get("description") or ""),
                metadata_={"scene_fragments": self._scene_fragments(str(row.get("kind") or ""))},
            )
            session.add(location)
            await session.flush()
            locations[location.kind] = location
        return locations

    async def _create_child(
        self,
        session: AsyncSession,
        world: SimulationWorld,
        locations: dict[str, WorldLocation],
        child: dict[str, Any],
    ) -> SimAgent:
        persona = Persona(
            name=str(child["name"]),
            description=str(child.get("description") or ""),
            persona_type="fictional_persona",
            consent_confirmed=False,
            persona_block=str(child.get("persona_block") or ""),
            human_block=str(child.get("human_block") or "用户是观察者。"),
            status="active",
        )
        session.add(persona)
        await session.flush()
        home = locations["home"]
        agent = SimAgent(
            world_id=world.id,
            persona_id=persona.id,
            name=persona.name,
            status="active",
            home_location_id=home.id,
            current_location_id=home.id,
            goals={"mvp": "按半天观察行动、经历、关系和成长趋势。"},
            traits={**(child.get("traits") or {}), "role": "child"},
            metadata_={"role": "child"},
        )
        session.add(agent)
        await session.flush()
        state = AgentState(
            agent_id=agent.id,
            needs=self._normalize_needs(child.get("needs") or default_needs()),
            mood="calm",
            plan={"step_granularity": "half_day", "routine": "home_kindergarten_community"},
            current_action="等待第一段半天经历",
            metadata_={
                "development": self._normalize_development(child.get("development") or default_development(agent.traits.get("age_months", 48))),
                "key_memories": [],
                "half_day_summaries": [],
            },
        )
        session.add(state)
        agent.state = state
        await session.flush()
        return agent

    async def _create_npcs(
        self,
        session: AsyncSession,
        world: SimulationWorld,
        locations: dict[str, WorldLocation],
        rows: list[dict[str, Any]],
    ) -> list[SimAgent]:
        agents: list[SimAgent] = []
        for row in rows:
            role = str(row.get("role") or "npc")
            location = locations["kindergarten"] if role in {"teacher", "peer"} else locations["home"]
            persona = Persona(
                name=str(row.get("name") or row.get("display_label") or role),
                description=str(row.get("description") or ""),
                persona_type="fictional_persona",
                consent_confirmed=False,
                persona_block=f"{row.get('description') or row.get('name')}。这是儿童成长模拟中的虚构 NPC。",
                human_block="用户是观察者。",
                status="active",
            )
            session.add(persona)
            await session.flush()
            agent = SimAgent(
                world_id=world.id,
                persona_id=persona.id,
                name=persona.name,
                status="active",
                home_location_id=location.id,
                current_location_id=location.id,
                goals={"npc_role": role},
                traits={**(row.get("traits") or {}), "role": role, "display_label": row.get("display_label") or persona.name},
                metadata_={"role": role, "relationship_type": row.get("relationship_type") or role},
            )
            session.add(agent)
            await session.flush()
            session.add(AgentState(agent_id=agent.id, mood="neutral", metadata_={"role": role}))
            agents.append(agent)
        await session.flush()
        return agents

    async def _create_relationships(
        self,
        session: AsyncSession,
        world: SimulationWorld,
        child: SimAgent,
        npcs: list[SimAgent],
        rows: list[dict[str, Any]],
    ) -> None:
        row_by_name = {str(row.get("npc_name") or row.get("name") or ""): row for row in rows if isinstance(row, dict)}
        for npc in npcs:
            role = str(npc.metadata_.get("relationship_type") or npc.metadata_.get("role") or "npc")
            row = row_by_name.get(npc.name, {})
            metrics = self._initial_relationship_metrics(role)
            if isinstance(row.get("metrics"), dict):
                metrics.update({key: clamp(value) for key, value in row["metrics"].items() if isinstance(value, int | float)})
            session.add(
                AgentRelationship(
                    world_id=world.id,
                    child_agent_id=child.id,
                    npc_agent_id=npc.id,
                    relationship_type=role,
                    metrics=metrics,
                    evidence_buffer=[],
                    confidence=0.6,
                    last_summary=f"{child.name} 与 {npc.name} 的关系处于初始观察阶段。",
                )
            )

    def _create_rules(self, session: AsyncSession, world: SimulationWorld) -> None:
        for priority, title, content in [
            (1, "儿童安全边界", "只生成温和、可恢复的日常挫折；不主动生成严重伤害、虐待、长期霸凌或诊断式结论。"),
            (5, "成长更新边界", "成长分数由规则层裁剪，每半天积累证据，每 14 step 结算一次。"),
            (10, "干预边界", "普通观察流程只能通过环境、规则、成人行为或 NPC 行为间接影响儿童状态。"),
        ]:
            session.add(CommunityRule(world_id=world.id, title=title, content=content, priority=priority, metadata_={"world_type": WORLD_TYPE}))

    def _create_random_event_templates(self, session: AsyncSession, world: SimulationWorld) -> None:
        templates = [
            ("天气变化", "户外活动前云层变厚，活动需要稍作调整。", "info", ["motor_ability", "emotional_regulation"]),
            ("身体小不适", "儿童表现出轻微疲惫或不舒服，成人温和观察并调整节奏。", "warning", ["self_care_habits", "emotional_regulation"]),
            ("玩具材料变化", "常用玩具或材料发生变化，引发新的探索或轻微失落。", "info", ["cognitive_attention", "language_communication"]),
            ("同伴邀请", "一名同伴邀请儿童加入游戏。", "info", ["social_cooperation", "language_communication"]),
            ("同伴冲突", "两个孩子对玩具或规则产生轻微分歧，老师提供修复机会。", "warning", ["social_cooperation", "emotional_regulation"]),
            ("老师表扬提醒", "老师对儿童的尝试给出表扬或清晰提醒。", "info", ["cognitive_attention", "self_care_habits"]),
            ("家庭作息波动", "家庭作息有轻微变化，需要儿童适应新的过渡。", "warning", ["emotional_regulation", "self_care_habits"]),
            ("社区偶遇", "散步时遇到熟悉邻里或新的自然观察机会。", "info", ["language_communication", "social_cooperation"]),
        ]
        for index, (name, prompt, severity, domains) in enumerate(templates, start=1):
            session.add(
                RandomEventTemplate(
                    world_id=world.id,
                    name=name,
                    trigger={"min_tick": 1, "every_n_ticks": index + 2, "domains": domains},
                    probability=0.18,
                    cooldown=HALF_DAY_MINUTES * 2,
                    severity=severity,
                    effect_prompt=prompt,
                    status="active",
                )
            )

    async def _persist_initial_memories(self, session: AsyncSession, child: SimAgent, memories: list[Any]) -> None:
        event = Event(
            persona_id=child.persona_id,
            conversation_id=None,
            event_type="child_world_initial_memory",
            source="child_world_draft",
            payload={"memory_count": len(memories), "agent_id": child.id},
        )
        session.add(event)
        await session.flush()
        for content in memories:
            text = str(content).strip()
            if not text:
                continue
            session.add(
                MemoryRecord(
                    persona_id=child.persona_id,
                    counterparty_user_id=None,
                    scope="persona",
                    subject=f"persona:{child.persona_id}",
                    memory_type="fact",
                    content=text,
                    confidence=0.75,
                    sensitivity="normal",
                    decision="approved",
                    source_event_id=event.id,
                    metadata_={"world_type": WORLD_TYPE, "agent_id": child.id, "generated": True},
                )
            )

    def _scene_fragments(self, kind: str) -> list[str]:
        return {
            "home": ["起床准备", "用餐", "亲子互动", "自由玩耍", "洗漱整理", "睡前/入睡"],
            "kindergarten": ["入园/分离", "集体活动", "自由游戏", "餐点/午休", "户外活动"],
            "community": ["散步探索", "游乐设施", "自然观察", "邻里互动", "温和突发小事件"],
        }.get(kind, [])

    def _normalize_needs(self, needs: dict[str, Any]) -> dict[str, int]:
        base = default_needs()
        base.update({key: clamp(value) for key, value in needs.items() if key in NEED_KEYS and isinstance(value, int | float)})
        return base

    def _normalize_development(self, development: dict[str, Any]) -> dict[str, dict[str, Any]]:
        normalized = default_development(48)
        for key in DEVELOPMENT_DOMAINS:
            row = development.get(key) if isinstance(development.get(key), dict) else {}
            normalized[key] = {
                "score": clamp(row.get("score", normalized[key]["score"])),
                "trend": str(row.get("trend") or "stable"),
                "evidence_buffer": row.get("evidence_buffer") if isinstance(row.get("evidence_buffer"), list) else [],
                "confidence": max(0, min(1, float(row.get("confidence") or normalized[key]["confidence"]))),
            }
        return normalized

    def _initial_relationship_metrics(self, role: str) -> dict[str, int]:
        metrics = {key: 55 for key in CORE_RELATIONSHIP_METRICS}
        metrics["tension"] = 12
        if role == "caregiver":
            metrics.update({"familiarity": 78, "warmth": 72, "trust_security": 70, "care_consistency": 68, "separation_comfort": 58})
        elif role == "teacher":
            metrics.update({"familiarity": 42, "warmth": 54, "trust_security": 50, "guidance_acceptance": 52, "classroom_comfort": 50})
        elif role == "peer":
            metrics.update({"familiarity": 36, "warmth": 48, "trust_security": 42, "play_preference": 48, "cooperation_fit": 46})
        return metrics


class ChildGrowthStepper:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.adapter = ConcordiaAdapter()
        self.projector = StateProjector()
        self.memory_writer = SimulationMemoryWriter()
        self.random_events = RandomEventScheduler()
        self.rulebook = Rulebook()
        self.safety = ChildSafetyPolicy()

    async def step(self, session: AsyncSession, world: SimulationWorld) -> SimulationStepResponse:
        tick_no = world.tick_no + 1
        reference_time = world.clock_time + timedelta(minutes=self.settings.simulation_step_minutes)
        rng = random.Random(f"{world.seed}:{tick_no}:child")

        locations = (
            await session.execute(select(WorldLocation).where(WorldLocation.world_id == world.id).order_by(WorldLocation.name))
        ).scalars().all()
        agents = (
            await session.execute(
                select(SimAgent)
                .options(selectinload(SimAgent.persona), selectinload(SimAgent.state))
                .where(SimAgent.world_id == world.id, SimAgent.status == "active")
                .order_by(SimAgent.name)
            )
        ).scalars().all()
        child = self._child_agent(world, list(agents))
        agent_by_id = {agent.id: agent for agent in agents}
        state = await self._ensure_state(session, child)
        relationships = (
            await session.execute(
                select(AgentRelationship).where(AgentRelationship.world_id == world.id, AgentRelationship.child_agent_id == child.id)
            )
        ).scalars().all()
        rules = (
            await session.execute(select(CommunityRule).where(CommunityRule.world_id == world.id).order_by(CommunityRule.priority))
        ).scalars().all()
        templates = (
            await session.execute(select(RandomEventTemplate).where(RandomEventTemplate.world_id == world.id).order_by(RandomEventTemplate.name))
        ).scalars().all()
        interventions = (
            await session.execute(
                select(UserIntervention)
                .where(UserIntervention.world_id == world.id, UserIntervention.status == "pending")
                .order_by(UserIntervention.created_at)
            )
        ).scalars().all()
        recent_events = (
            await session.execute(
                select(SimulationEvent)
                .where(SimulationEvent.world_id == world.id)
                .order_by(desc(SimulationEvent.reference_time), desc(SimulationEvent.created_at))
                .limit(12)
            )
        ).scalars().all()

        sanitized_interventions, intervention_flags = self._intervention_context(list(interventions))
        schedule = self._schedule_for_step(tick_no)
        intervention_plan = self._intervention_plan(
            sanitized_interventions,
            schedule=schedule,
            locations=list(locations),
            relationships=list(relationships),
            agent_by_id=agent_by_id,
        )
        schedule = self._schedule_with_intervention(schedule, intervention_plan)
        location = self._location_for_schedule(schedule, list(locations))
        if intervention_plan and intervention_plan.get("location_id"):
            location = next((item for item in locations if item.id == intervention_plan["location_id"]), location)
        random_event = self._random_event(list(templates), tick_no=tick_no, reference_time=reference_time, rng=rng)
        involved_relationships = self._involved_relationships(schedule, list(relationships), rng)
        involved_relationships = self._relationships_for_intervention(
            intervention_plan,
            base_relationships=involved_relationships,
            relationships=list(relationships),
            agent_by_id=agent_by_id,
        )
        involved_actors = self._relationship_actors(involved_relationships, agent_by_id)
        action_text = self._action_text(child, schedule, location, random_event, sanitized_interventions, involved_actors, intervention_plan)
        context = self._context(
            world=world,
            child=child,
            state=state,
            location=location,
            schedule=schedule,
            locations=list(locations),
            relationships=list(relationships),
            involved_relationships=involved_relationships,
            involved_actors=involved_actors,
            agent_by_id=agent_by_id,
            rules=self.rulebook.active_rules(list(rules), now=world.clock_time),
            recent_events=list(recent_events),
            interventions=sanitized_interventions,
            intervention_plan=intervention_plan,
            random_event=random_event,
        )

        action = SimulationAction(world_id=world.id, agent_id=child.id, action_text=action_text, status="proposed", source="child_growth", context=context)
        session.add(action)
        await session.flush()
        raw_outcome = await self.adapter.resolve_action(context=context, action_text=action_text)
        outcome = self._normalize_outcome(
            raw_outcome,
            child=child,
            schedule=schedule,
            location=location,
            random_event=random_event,
            risk_flags=intervention_flags,
            tick_no=tick_no,
            involved_relationships=involved_relationships,
            involved_actors=involved_actors,
            interventions=sanitized_interventions,
            intervention_plan=intervention_plan,
        )
        important_memory_writes = self._important_memory_writes(
            child=child,
            outcome=outcome,
            random_event=random_event,
            interventions=sanitized_interventions,
        )
        if important_memory_writes:
            outcome["memory_writes"] = [*outcome["memory_writes"], *important_memory_writes]

        self._apply_child_state(state, child=child, location=location, outcome=outcome, tick_no=tick_no)
        relationship_changes = self._apply_relationship_evidence(involved_relationships, outcome=outcome, tick_no=tick_no)
        if random_event is not None:
            random_event.last_triggered_at = reference_time
        action.status = "needs_review" if outcome["needs_review"] else "completed"
        action.result = outcome

        event = SimulationEvent(
            world_id=world.id,
            tick_no=tick_no,
            event_type="child_half_day",
            source="child_growth",
            status="needs_review" if outcome["needs_review"] else "completed",
            reference_time=reference_time,
            actors=[child.id, *[relationship.npc_agent_id for relationship in involved_relationships]],
            location_id=location.id if location else child.current_location_id,
            payload={
                "world_id": world.id,
                "action_id": action.id,
                "main_action": outcome["main_action"],
                "action_text": action_text,
                "sub_fragments": outcome["sub_fragments"],
                "observed_facts": outcome["observed_facts"],
                "child_interpretation": outcome["child_interpretation"],
                "gm_interpretation": outcome["gm_interpretation"],
                "state_update_evidence": outcome["state_update_evidence"],
                "half_day_summary": outcome["half_day_summary"],
                "life_slice": outcome["life_slice"],
                "summary": outcome["half_day_summary"],
                "suggested_updates": outcome["suggested_updates"],
                "relationship_changes": relationship_changes,
                "development": state.metadata_.get("development", {}),
                "needs": state.needs,
                "risk_flags": outcome["risk_flags"],
                "needs_review": outcome["needs_review"],
                "raw_outcome": outcome["raw_outcome"],
                "memory_writes": outcome["memory_writes"],
                "gm_source": outcome["gm_source"],
                "concordia_wrapper_error": outcome["concordia_wrapper_error"],
                "random_event": self._template_context(random_event) if random_event else None,
                "interventions": sanitized_interventions,
                "intervention_plan": intervention_plan,
                "intervention_effect_summary": self._intervention_effect_summary(intervention_plan, involved_actors),
            },
        )
        session.add(event)
        await session.flush()
        await self._persist_memory(session, event)

        created_events = [event]
        report_event = await self._maybe_generate_report(session, world=world, child=child, state=state, relationships=list(relationships), tick_no=tick_no, source_event=event)
        if report_event is not None:
            created_events.append(report_event)

        for intervention in interventions:
            intervention.status = "applied"
            intervention.result_event_id = event.id
        world.tick_no = tick_no
        world.clock_time = reference_time
        await session.flush()
        await self._snapshot(session, world=world, child=child, event_cursor=created_events[-1].id)
        state_projection = await self.projector.project(session, world.id)
        return SimulationStepResponse(
            world=SimulationWorldResponse.model_validate(world),
            events=[SimulationEventResponse.model_validate(item) for item in created_events],
            state=state_projection,
        )

    def _child_agent(self, world: SimulationWorld, agents: list[SimAgent]) -> SimAgent:
        child_id = (world.settings or {}).get("child_agent_id")
        for agent in agents:
            if agent.id == child_id or agent.metadata_.get("role") == "child" or agent.traits.get("role") == "child":
                return agent
        raise ValueError("child agent not found")

    async def _ensure_state(self, session: AsyncSession, child: SimAgent) -> AgentState:
        if child.state is not None:
            if not child.state.needs:
                child.state.needs = default_needs()
            metadata = dict(child.state.metadata_ or {})
            metadata.setdefault("development", default_development(child.traits.get("age_months", 48)))
            metadata.setdefault("key_memories", [])
            metadata.setdefault("half_day_summaries", [])
            child.state.metadata_ = metadata
            return child.state
        state = AgentState(agent_id=child.id, needs=default_needs(), mood="calm", metadata_={"development": default_development(48), "key_memories": [], "half_day_summaries": []})
        session.add(state)
        await session.flush()
        child.state = state
        return state

    def _schedule_for_step(self, tick_no: int) -> dict[str, Any]:
        index = (tick_no - 1) % 14
        day_index = index // 2
        half = "morning" if index % 2 == 0 else "evening"
        weekday = day_index < 5
        if weekday and half == "morning":
            return {"day_index": day_index, "half": half, "scene": "kindergarten", "main": "入园、集体活动和自由游戏", "domains": ["language_communication", "social_cooperation", "cognitive_attention"]}
        if weekday:
            return {"day_index": day_index, "half": half, "scene": "home", "main": "回家后的用餐、亲子互动和整理", "domains": ["self_care_habits", "emotional_regulation", "language_communication"]}
        if half == "morning":
            return {"day_index": day_index, "half": half, "scene": "community", "main": "户外探索和自然观察", "domains": ["motor_ability", "language_communication", "cognitive_attention"]}
        return {"day_index": day_index, "half": half, "scene": "home", "main": "自由玩耍、洗漱和睡前过渡", "domains": ["self_care_habits", "emotional_regulation", "social_cooperation"]}

    def _location_for_schedule(self, schedule: dict[str, Any], locations: list[WorldLocation]) -> WorldLocation | None:
        scene = schedule["scene"]
        for location in locations:
            if location.kind == scene:
                return location
        return locations[0] if locations else None

    def _random_event(
        self,
        templates: list[RandomEventTemplate],
        *,
        tick_no: int,
        reference_time: datetime,
        rng: random.Random,
    ) -> RandomEventTemplate | None:
        due = self.random_events.due_templates(templates, tick_no=tick_no, clock_time=reference_time, rng=rng)
        return due[0] if due else None

    def _involved_relationships(
        self,
        schedule: dict[str, Any],
        relationships: list[AgentRelationship],
        rng: random.Random,
    ) -> list[AgentRelationship]:
        if schedule["scene"] == "kindergarten":
            preferred = [rel for rel in relationships if rel.relationship_type in {"teacher", "peer"}]
        elif schedule["scene"] == "home":
            preferred = [rel for rel in relationships if rel.relationship_type == "caregiver"]
        else:
            preferred = [rel for rel in relationships if rel.relationship_type in {"caregiver", "peer"}]
        if not preferred:
            preferred = relationships
        return rng.sample(preferred, k=min(len(preferred), 2)) if preferred else []

    def _intervention_plan(
        self,
        interventions: list[dict[str, Any]],
        *,
        schedule: dict[str, Any],
        locations: list[WorldLocation],
        relationships: list[AgentRelationship],
        agent_by_id: dict[str, SimAgent],
    ) -> dict[str, Any] | None:
        if not interventions:
            return None
        primary = interventions[0]
        payload = dict(primary.get("payload") or {})
        text = self._clean_intervention_value(primary.get("text") or payload.get("text") or payload.get("description"))
        location_id = self._clean_intervention_value(payload.get("location_id"), limit=80)
        location = next((item for item in locations if item.id == location_id), None) if location_id else None
        agent_id = self._clean_intervention_value(payload.get("agent_id"), limit=80)
        target_role = self._normalize_target_role(payload.get("target_role") or payload.get("relationship_type") or payload.get("role"))
        matched_relationship = self._relationship_for_agent(agent_id, relationships) if agent_id else None
        if matched_relationship is None and text:
            matched_relationship = self._relationship_from_text(text, relationships, agent_by_id)
        if matched_relationship is not None:
            agent_id = matched_relationship.npc_agent_id
            target_role = target_role or matched_relationship.relationship_type
        if not target_role:
            target_role = self._infer_target_role(str(primary.get("type") or ""), text)

        scene = self._normalize_scene(payload.get("scene") or payload.get("target_scene"))
        if location is not None:
            scene = location.kind
        elif not scene and target_role in {"teacher", "peer"}:
            scene = "kindergarten"

        activity_goal = self._clean_intervention_value(payload.get("activity_goal") or payload.get("goal") or payload.get("activity"), limit=160)
        guidance_style = self._clean_intervention_value(payload.get("guidance_style") or payload.get("style") or payload.get("adult_behavior"), limit=160)
        if not guidance_style and text:
            guidance_style = self._infer_guidance_style(text)

        return {
            "id": primary.get("id"),
            "type": primary.get("type"),
            "text": text,
            "location_id": location.id if location is not None else (location_id or None),
            "location_kind": location.kind if location is not None else None,
            "scene": scene or None,
            "target_role": target_role,
            "agent_id": agent_id or None,
            "activity_goal": activity_goal or None,
            "guidance_style": guidance_style or None,
            "base_scene": schedule.get("scene"),
            "base_main": schedule.get("main"),
            "applies_to": "next_step",
        }

    def _schedule_with_intervention(self, schedule: dict[str, Any], intervention_plan: dict[str, Any] | None) -> dict[str, Any]:
        if not intervention_plan:
            return schedule
        updated = dict(schedule)
        scene = self._normalize_scene(intervention_plan.get("scene"))
        if scene:
            updated["scene"] = scene
            updated["domains"] = self._domains_for_scene(scene)
        activity_goal = str(intervention_plan.get("activity_goal") or "").strip()
        if activity_goal:
            updated["main"] = activity_goal
        updated["intervention_override"] = True
        return updated

    def _relationships_for_intervention(
        self,
        intervention_plan: dict[str, Any] | None,
        *,
        base_relationships: list[AgentRelationship],
        relationships: list[AgentRelationship],
        agent_by_id: dict[str, SimAgent],
    ) -> list[AgentRelationship]:
        if not intervention_plan:
            return base_relationships
        selected: list[AgentRelationship] = []
        agent_id = str(intervention_plan.get("agent_id") or "").strip()
        target_role = str(intervention_plan.get("target_role") or "").strip()
        text = str(intervention_plan.get("text") or "").strip()
        for candidate in [
            self._relationship_for_agent(agent_id, relationships) if agent_id else None,
            self._relationship_from_text(text, relationships, agent_by_id) if text else None,
            self._relationship_for_role(target_role, relationships) if target_role else None,
        ]:
            if candidate is not None and candidate.id not in {item.id for item in selected}:
                selected.append(candidate)
        for relationship in base_relationships:
            if relationship.id not in {item.id for item in selected}:
                selected.append(relationship)
        return selected[:3] if selected else base_relationships

    def _clean_intervention_value(self, value: Any, *, limit: int = 240) -> str:
        return str(value or "").strip()[:limit]

    def _normalize_scene(self, value: Any) -> str:
        scene = str(value or "").strip().lower()
        aliases = {
            "kindergarten": "kindergarten",
            "school": "kindergarten",
            "classroom": "kindergarten",
            "幼儿园": "kindergarten",
            "教室": "kindergarten",
            "home": "home",
            "family": "home",
            "家": "home",
            "家庭": "home",
            "community": "community",
            "outdoor": "community",
            "park": "community",
            "社区": "community",
            "户外": "community",
        }
        return aliases.get(scene, scene if scene in {"kindergarten", "home", "community"} else "")

    def _domains_for_scene(self, scene: str) -> list[str]:
        if scene == "kindergarten":
            return ["language_communication", "social_cooperation", "cognitive_attention"]
        if scene == "community":
            return ["motor_ability", "language_communication", "cognitive_attention"]
        return ["self_care_habits", "emotional_regulation", "language_communication"]

    def _normalize_target_role(self, value: Any) -> str:
        raw = str(value or "").strip()
        lowered = raw.lower()
        if lowered in {"caregiver", "adult", "parent", "family"} or raw in {"成人", "家长", "照护者", "家庭成人", "爸爸", "妈妈"}:
            return "caregiver"
        if lowered in {"teacher", "educator"} or "老师" in raw:
            return "teacher"
        if lowered in {"peer", "classmate", "friend"} or raw in {"同伴", "小朋友", "伙伴"}:
            return "peer"
        return lowered if lowered in {"caregiver", "teacher", "peer"} else ""

    def _infer_target_role(self, intervention_type: str, text: str) -> str:
        lowered = text.lower()
        if "老师" in text or "teacher" in lowered:
            return "teacher"
        if any(token in text for token in ("同伴", "小朋友", "伙伴")) or "peer" in lowered:
            return "peer"
        if any(token in text for token in ("爸爸", "妈妈", "奶奶", "爷爷", "外婆", "外公", "家长", "照护者", "成人")):
            return "caregiver"
        if intervention_type == "adult_behavior":
            return "caregiver"
        return ""

    def _infer_guidance_style(self, text: str) -> str:
        if "蹲" in text or "平视" in text:
            return "蹲下来平视提示"
        if "慢" in text or "放慢" in text:
            return "放慢节奏提示"
        if "提醒" in text:
            return "清晰温和提醒"
        return ""

    def _relationship_for_agent(self, agent_id: str, relationships: list[AgentRelationship]) -> AgentRelationship | None:
        if not agent_id:
            return None
        return next((relationship for relationship in relationships if relationship.npc_agent_id == agent_id), None)

    def _relationship_for_role(self, relationship_type: str, relationships: list[AgentRelationship]) -> AgentRelationship | None:
        if not relationship_type:
            return None
        return next((relationship for relationship in relationships if relationship.relationship_type == relationship_type), None)

    def _relationship_from_text(
        self,
        text: str,
        relationships: list[AgentRelationship],
        agent_by_id: dict[str, SimAgent],
    ) -> AgentRelationship | None:
        if not text:
            return None
        for relationship in relationships:
            agent = agent_by_id.get(relationship.npc_agent_id)
            if agent is None:
                continue
            traits = dict(agent.traits or {})
            labels = [agent.name, str(traits.get("display_label") or "")]
            if any(label and label in text for label in labels):
                return relationship
        return None

    def _intervention_effect_summary(self, intervention_plan: dict[str, Any] | None, involved_actors: list[dict[str, Any]]) -> str:
        if not intervention_plan:
            return ""
        actor_text = self._actor_text(
            involved_actors,
            fallback=self._relationship_role_label(str(intervention_plan.get("target_role") or ""), "") or "相关成人/NPC",
        )
        goal = str(intervention_plan.get("activity_goal") or "本次半天活动")
        style = str(intervention_plan.get("guidance_style") or "温和间接支持")
        text = str(intervention_plan.get("text") or "")
        return f"下一步优先执行间接干预：由{actor_text}以“{style}”引导儿童参与“{goal}”。{text}"

    def _relationship_actors(self, relationships: list[AgentRelationship], agent_by_id: dict[str, SimAgent]) -> list[dict[str, Any]]:
        actors: list[dict[str, Any]] = []
        for relationship in relationships:
            agent = agent_by_id.get(relationship.npc_agent_id)
            traits = dict(agent.traits or {}) if agent is not None else {}
            display_label = str(traits.get("display_label") or (agent.name if agent is not None else relationship.npc_agent_id[:8])).strip()
            relationship_type = relationship.relationship_type
            actors.append(
                {
                    "relationship_id": relationship.id,
                    "agent_id": relationship.npc_agent_id,
                    "relationship_type": relationship_type,
                    "name": agent.name if agent is not None else display_label,
                    "display_label": display_label,
                    "role_label": self._relationship_role_label(relationship_type, display_label),
                }
            )
        return actors

    def _relationship_role_label(self, relationship_type: str, display_label: str) -> str:
        if relationship_type == "teacher":
            return display_label or "老师"
        if relationship_type == "peer":
            return display_label or "同伴"
        if relationship_type == "caregiver":
            return display_label or "熟悉成人"
        return display_label or relationship_type

    def _actor_text(self, actors: list[dict[str, Any]], *, fallback: str = "身边成人") -> str:
        labels: list[str] = []
        for actor in actors:
            label = str(actor.get("display_label") or actor.get("name") or "").strip()
            if label and label not in labels:
                labels.append(label)
        if not labels:
            return fallback
        return "、".join(labels[:3])

    def _actors_by_type(self, actors: list[dict[str, Any]], relationship_type: str) -> list[dict[str, Any]]:
        return [actor for actor in actors if actor.get("relationship_type") == relationship_type]

    def _first_actor_label(self, actors: list[dict[str, Any]], relationship_type: str | None = None) -> str:
        rows = self._actors_by_type(actors, relationship_type) if relationship_type else actors
        for actor in rows:
            label = str(actor.get("display_label") or actor.get("name") or "").strip()
            if label:
                return label
        return ""

    def _family_labels(self, child: SimAgent) -> list[str]:
        family = child.traits.get("family_structure") if isinstance(child.traits, dict) else {}
        if not isinstance(family, dict):
            return []
        labels: list[str] = []
        for value in family.values():
            if not isinstance(value, dict):
                continue
            label = str(value.get("display_label") or "").strip()
            if label and label not in labels:
                labels.append(label)
        return labels

    def _caregiver_replacement(self, *, child: SimAgent, involved_actors: list[dict[str, Any]]) -> str:
        for label in [
            self._first_actor_label(involved_actors, "caregiver"),
            *self._family_labels(child),
        ]:
            if label and "照护者" not in label:
                return label
        return ""

    def _replace_generic_caregiver(self, text: str, *, child: SimAgent, involved_actors: list[dict[str, Any]]) -> str:
        replacement = self._caregiver_replacement(child=child, involved_actors=involved_actors)
        if not replacement:
            return text
        return text.replace("主要照护者", replacement).replace("照护者", replacement)

    def _intervention_context(self, interventions: list[UserIntervention]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        rows: list[dict[str, Any]] = []
        flags: list[dict[str, str]] = []
        for intervention in interventions:
            payload = dict(intervention.payload or {})
            text = str(payload.get("text") or payload.get("description") or "")
            sanitized, found = self.safety.sanitize_event_text(text)
            flags.extend(found)
            rows.append(
                {
                    "id": intervention.id,
                    "type": intervention.intervention_type,
                    "text": sanitized,
                    "payload": {**payload, "text": sanitized},
                    "created_at": intervention.created_at.isoformat(),
                }
            )
        return rows, flags

    def _action_text(
        self,
        child: SimAgent,
        schedule: dict[str, Any],
        location: WorldLocation | None,
        random_event: RandomEventTemplate | None,
        interventions: list[dict[str, Any]],
        involved_actors: list[dict[str, Any]],
        intervention_plan: dict[str, Any] | None,
    ) -> str:
        place = location.name if location else schedule["scene"]
        if involved_actors:
            actor_text = self._actor_text(involved_actors)
            parts = [f"{child.name}在{place}和{actor_text}经历半天：{schedule['main']}。"]
        elif schedule["scene"] == "home" and self._family_labels(child):
            actor_text = "、".join(self._family_labels(child)[:2])
            parts = [f"{child.name}在{place}和{actor_text}经历半天：{schedule['main']}。"]
        else:
            parts = [f"{child.name}在{place}经历半天：{schedule['main']}。"]
        if random_event is not None:
            parts.append(f"温和随机事件：{random_event.effect_prompt}")
        if interventions:
            parts.append(f"观察者注入事件：{interventions[0]['text']}")
        if intervention_plan:
            goal = str(intervention_plan.get("activity_goal") or schedule["main"])
            style = str(intervention_plan.get("guidance_style") or "温和间接支持")
            parts.append(f"本步优先执行干预计划：用“{style}”引导{child.name}参与“{goal}”。")
        return " ".join(parts)

    def _context(
        self,
        *,
        world: SimulationWorld,
        child: SimAgent,
        state: AgentState,
        location: WorldLocation | None,
        schedule: dict[str, Any],
        locations: list[WorldLocation],
        relationships: list[AgentRelationship],
        involved_relationships: list[AgentRelationship],
        involved_actors: list[dict[str, Any]],
        agent_by_id: dict[str, SimAgent],
        rules: list[CommunityRule],
        recent_events: list[SimulationEvent],
        interventions: list[dict[str, Any]],
        intervention_plan: dict[str, Any] | None,
        random_event: RandomEventTemplate | None,
    ) -> dict[str, Any]:
        return {
            "world": {"id": world.id, "type": WORLD_TYPE, "tick_no": world.tick_no, "clock_time": world.clock_time.isoformat(), "seed": world.seed},
            "child": {
                "id": child.id,
                "name": child.name,
                "traits": child.traits,
                "needs": state.needs,
                "development": state.metadata_.get("development", {}),
                "mood": state.mood,
            },
            "schedule": schedule,
            "location": self._location_context(location),
            "locations": [self._location_context(item) for item in locations],
            "relationships": [self._relationship_context(item, agent_by_id) for item in relationships],
            "involved_relationships": [self._relationship_context(item, agent_by_id) for item in involved_relationships],
            "involved_actors": involved_actors,
            "caregiver_display_labels": self._family_labels(child),
            "rules": self.rulebook.to_context(rules),
            "recent_events": [{"tick_no": event.tick_no, "summary": event.payload.get("summary") or event.payload.get("half_day_summary")} for event in recent_events],
            "interventions": interventions,
            "intervention_plan": intervention_plan,
            "random_event": self._template_context(random_event) if random_event else None,
            "output_contract": {
                "required": ["observed_facts", "child_interpretation", "gm_interpretation", "state_update_evidence", "half_day_summary", "life_slice"],
                "life_slice": {"scene_description": "one concrete scene", "dialogue": "10-20 turns, child centered, no metrics or GM explanation"},
                "state_policy": "LLM suggests meaning only; backend clamps needs, development and relationships.",
            },
        }

    def _location_context(self, location: WorldLocation | None) -> dict[str, Any] | None:
        if location is None:
            return None
        return {"id": location.id, "name": location.name, "kind": location.kind, "description": location.description}

    def _relationship_context(self, relationship: AgentRelationship, agent_by_id: dict[str, SimAgent] | None = None) -> dict[str, Any]:
        agent = agent_by_id.get(relationship.npc_agent_id) if agent_by_id else None
        traits = dict(agent.traits or {}) if agent is not None else {}
        display_label = str(traits.get("display_label") or (agent.name if agent is not None else relationship.npc_agent_id[:8]))
        return {
            "id": relationship.id,
            "npc_agent_id": relationship.npc_agent_id,
            "relationship_type": relationship.relationship_type,
            "npc_name": agent.name if agent is not None else "",
            "display_label": display_label,
            "role_label": self._relationship_role_label(relationship.relationship_type, display_label),
            "metrics": relationship.metrics,
            "last_summary": relationship.last_summary,
        }

    def _template_context(self, template: RandomEventTemplate | None) -> dict[str, Any] | None:
        if template is None:
            return None
        return {"id": template.id, "name": template.name, "severity": template.severity, "prompt": template.effect_prompt, "trigger": template.trigger}

    def _normalize_outcome(
        self,
        raw: dict[str, Any],
        *,
        child: SimAgent,
        schedule: dict[str, Any],
        location: WorldLocation | None,
        random_event: RandomEventTemplate | None,
        risk_flags: list[dict[str, str]],
        tick_no: int,
        involved_relationships: list[AgentRelationship],
        involved_actors: list[dict[str, Any]],
        interventions: list[dict[str, Any]],
        intervention_plan: dict[str, Any] | None,
    ) -> dict[str, Any]:
        sub_fragments = raw.get("sub_fragments") if isinstance(raw.get("sub_fragments"), list) else []
        if not sub_fragments:
            sub_fragments = self._sub_fragments(schedule, random_event, involved_actors, intervention_plan)
        fallback = bool(raw.get("fallback_reason"))
        unstructured = raw.get("gm_source") == "unstructured"
        deterministic_summary = self._fallback_half_day_summary(
            child=child,
            schedule=schedule,
            location=location,
            sub_fragments=[str(item) for item in sub_fragments[:3]],
            random_event=random_event,
            interventions=interventions,
            tick_no=tick_no,
            involved_actors=involved_actors,
            intervention_plan=intervention_plan,
        )
        deterministic_life_slice = self._fallback_life_slice(
            child=child,
            schedule=schedule,
            location=location,
            sub_fragments=[str(item) for item in sub_fragments[:3]],
            random_event=random_event,
            interventions=interventions,
            tick_no=tick_no,
            involved_actors=involved_actors,
            intervention_plan=intervention_plan,
        )
        if fallback or unstructured:
            observed = self._fallback_observed_facts(
                child=child,
                schedule=schedule,
                location=location,
                sub_fragments=[str(item) for item in sub_fragments[:3]],
                random_event=random_event,
                interventions=interventions,
                involved_actors=involved_actors,
                intervention_plan=intervention_plan,
            )
            half_day_summary = deterministic_summary
            child_interpretation = self._child_voice(child, schedule, random_event, involved_actors=involved_actors, tick_no=tick_no)
            gm_interpretation = self._fallback_gm_interpretation(
                schedule=schedule,
                random_event=random_event,
                interventions=interventions,
                involved_relationships=involved_relationships,
                involved_actors=involved_actors,
                intervention_plan=intervention_plan,
            )
            state_update_evidence = self._fallback_state_update_evidence(
                schedule=schedule,
                location=location,
                sub_fragments=[str(item) for item in sub_fragments[:3]],
                random_event=random_event,
                interventions=interventions,
                involved_relationships=involved_relationships,
                intervention_plan=intervention_plan,
            )
            suggested_updates = self._fallback_suggested_updates(schedule=schedule, involved_relationships=involved_relationships)
            life_slice = deterministic_life_slice
        else:
            observed = raw.get("observed_facts") if isinstance(raw.get("observed_facts"), list) else []
            if not observed:
                observed = self._fallback_observed_facts(
                    child=child,
                    schedule=schedule,
                    location=location,
                    sub_fragments=[str(item) for item in sub_fragments[:3]],
                    random_event=random_event,
                    interventions=interventions,
                    involved_actors=involved_actors,
                    intervention_plan=intervention_plan,
                )
            half_day_summary = str(raw.get("half_day_summary") or raw.get("summary") or deterministic_summary)
            child_interpretation = str(raw.get("child_interpretation") or self._child_voice(child, schedule, random_event, involved_actors=involved_actors, tick_no=tick_no))
            gm_interpretation = str(raw.get("gm_interpretation") or self._fallback_gm_interpretation(schedule=schedule, random_event=random_event, interventions=interventions, involved_relationships=involved_relationships, involved_actors=involved_actors, intervention_plan=intervention_plan))
            state_update_evidence = raw.get("state_update_evidence") if isinstance(raw.get("state_update_evidence"), list) else []
            if not state_update_evidence:
                state_update_evidence = self._fallback_state_update_evidence(
                    schedule=schedule,
                    location=location,
                    sub_fragments=[str(item) for item in sub_fragments[:3]],
                    random_event=random_event,
                    interventions=interventions,
                    involved_relationships=involved_relationships,
                    intervention_plan=intervention_plan,
                )
            suggested_updates = raw.get("suggested_updates") if isinstance(raw.get("suggested_updates"), dict) else {}
            if not suggested_updates:
                suggested_updates = self._fallback_suggested_updates(schedule=schedule, involved_relationships=involved_relationships)
            life_slice = self._normalize_life_slice(raw.get("life_slice"), deterministic_life_slice, child=child, involved_actors=involved_actors)
        half_day_summary = self._replace_generic_caregiver(half_day_summary, child=child, involved_actors=involved_actors)
        child_interpretation = self._replace_generic_caregiver(child_interpretation, child=child, involved_actors=involved_actors)
        gm_interpretation = self._replace_generic_caregiver(gm_interpretation, child=child, involved_actors=involved_actors)
        observed = [self._replace_generic_caregiver(str(item), child=child, involved_actors=involved_actors) for item in observed[:5]]
        if intervention_plan and not any(isinstance(item, dict) and item.get("source") == "intervention_plan" for item in state_update_evidence):
            plan_evidence = {
                "source": "intervention_plan",
                "detail": self._intervention_effect_summary(intervention_plan, involved_actors),
                "activity_goal": intervention_plan.get("activity_goal"),
                "guidance_style": intervention_plan.get("guidance_style"),
                "target_role": intervention_plan.get("target_role"),
            }
            state_update_evidence = [*state_update_evidence[:4], plan_evidence]
        return {
            "accepted": bool(raw.get("accepted", True)),
            "main_action": str((intervention_plan or {}).get("activity_goal") or (schedule["main"] if fallback else raw.get("main_action") or schedule["main"])),
            "sub_fragments": [str(item) for item in sub_fragments[:3]],
            "observed_facts": observed,
            "child_interpretation": child_interpretation,
            "gm_interpretation": gm_interpretation,
            "state_update_evidence": state_update_evidence,
            "half_day_summary": half_day_summary,
            "life_slice": life_slice,
            "suggested_updates": suggested_updates,
            "risk_flags": risk_flags + (raw.get("risk_flags") if isinstance(raw.get("risk_flags"), list) else []),
            "needs_review": bool(raw.get("needs_review") or risk_flags),
            "raw_outcome": str(raw.get("raw_outcome") or ""),
            "memory_writes": raw.get("memory_writes") if isinstance(raw.get("memory_writes"), list) else [],
            "gm_source": str(raw.get("gm_source") or ("local_rule_fallback" if fallback else "unknown")),
            "concordia_wrapper_error": raw.get("concordia_wrapper_error"),
        }

    def _fallback_observed_facts(
        self,
        *,
        child: SimAgent,
        schedule: dict[str, Any],
        location: WorldLocation | None,
        sub_fragments: list[str],
        random_event: RandomEventTemplate | None,
        interventions: list[dict[str, Any]],
        involved_actors: list[dict[str, Any]],
        intervention_plan: dict[str, Any] | None,
    ) -> list[str]:
        place = location.name if location else schedule["scene"]
        actor_text = self._actor_text(involved_actors, fallback="身边成人")
        if involved_actors:
            facts = [f"{child.name}在{place}和{actor_text}进行半天主行动：{schedule['main']}。"]
        else:
            facts = [f"{child.name}在{place}进行半天主行动：{schedule['main']}。"]
        facts.extend(f"观察到子片段：{fragment}。" for fragment in sub_fragments[:2])
        if random_event is not None:
            facts.append(f"本半天出现温和随机事件：{random_event.name}。")
        if interventions:
            facts.append(f"观察者注入的间接事件已进入环境：{safe_memory_text(interventions[0].get('text'))}。")
        if intervention_plan and intervention_plan.get("activity_goal"):
            facts.append(f"本步活动目标已按干预调整为：{intervention_plan['activity_goal']}。")
        return facts[:5]

    def _fallback_half_day_summary(
        self,
        *,
        child: SimAgent,
        schedule: dict[str, Any],
        location: WorldLocation | None,
        sub_fragments: list[str],
        random_event: RandomEventTemplate | None,
        interventions: list[dict[str, Any]],
        tick_no: int,
        involved_actors: list[dict[str, Any]],
        intervention_plan: dict[str, Any] | None,
    ) -> str:
        place = location.name if location else schedule["scene"]
        actor_text = self._actor_text(involved_actors, fallback="身边成人")
        if not involved_actors and schedule["scene"] == "home" and self._family_labels(child):
            actor_text = "、".join(self._family_labels(child)[:2])
        scene_templates = {
            "kindergarten": [
                "{name}在{place}先完成入园过渡，再和{actors}参与{focus}，半天里有了具体互动的证据。",
                "{name}在{place}围绕{focus}展开活动，能看到分离适应、集体规则和自由游戏之间的切换。",
                "{name}在{place}经历了{focus}，留下了语言表达、注意跟随和合作尝试的观察点。",
            ],
            "home": [
                "{name}回到{place}后以{focus}为主，{actors}的回应和整理步骤构成了这半天的核心经历。",
                "{name}在{place}和{actors}围绕{focus}慢慢收束状态，半天记录重点落在安全感、自理和情绪恢复。",
                "{name}在{place}完成{focus}，能看到{actors}对节奏、表达和整理行为的支持。",
            ],
            "community": [
                "{name}在{place}和{actors}通过{focus}接触户外变化，半天记录集中在探索、身体活动和分享发现。",
                "{name}在{place}围绕{focus}展开观察，新的环境线索带来了运动、语言和注意证据。",
                "{name}在{place}完成{focus}，这半天更像一次温和的外部世界探索。",
            ],
        }
        focus = "、".join(sub_fragments[:2]) if sub_fragments else schedule["main"]
        templates = scene_templates.get(schedule["scene"], ["{name}在{place}完成{focus}，形成了可观察的半天经历。"])
        summary = templates[(tick_no - 1) % len(templates)].format(name=child.name, place=place, focus=focus, actors=actor_text)
        if random_event is not None:
            summary += f" 同时出现了“{random_event.name}”，为本次观察增加了轻微变化。"
        if interventions:
            summary += " 观察者注入的间接事件被纳入环境，但状态变化仍由后端规则裁剪。"
        if intervention_plan and intervention_plan.get("guidance_style"):
            summary += f" 本次引导方式按干预设置为“{intervention_plan['guidance_style']}”。"
        return summary

    def _fallback_life_slice(
        self,
        *,
        child: SimAgent,
        schedule: dict[str, Any],
        location: WorldLocation | None,
        sub_fragments: list[str],
        random_event: RandomEventTemplate | None,
        interventions: list[dict[str, Any]],
        tick_no: int,
        involved_actors: list[dict[str, Any]],
        intervention_plan: dict[str, Any] | None,
    ) -> dict[str, Any]:
        place = location.name if location else schedule["scene"]
        family_labels = self._family_labels(child)
        caregiver = self._first_actor_label(involved_actors, "caregiver") or (family_labels[(tick_no - 1) % len(family_labels)] if family_labels else "大人")
        other_family = next((label for label in family_labels if label != caregiver), caregiver)
        pickup_label = family_labels[0] if family_labels else caregiver
        teacher = self._first_actor_label(involved_actors, "teacher") or "老师"
        peer = self._first_actor_label(involved_actors, "peer") or "小伙伴"
        focus = str((intervention_plan or {}).get("activity_goal") or (sub_fragments[0] if sub_fragments else schedule["main"]))
        temperament_line = self._temperament_child_line(child)
        event_line = f"刚才有{random_event.name}，我看见了。" if random_event is not None else "我还想再试一次。"
        guided_goal = str((intervention_plan or {}).get("activity_goal") or focus)
        guided_style = str((intervention_plan or {}).get("guidance_style") or "慢慢来")

        if schedule["scene"] == "kindergarten":
            scene_description = f"{place}里，{child.name}在{teacher}和{peer}旁边慢慢进入活动，片段集中在{focus}。"
            dialogue = [
                {"speaker": teacher, "text": f"{child.name}，你可以先把小包放到自己的位置。"},
                {"speaker": child.name, "text": "我放这里吗？"},
                {"speaker": teacher, "text": "对，就是这个格子。"},
                {"speaker": child.name, "text": f"我想看一下{pickup_label}会不会来。"},
                {"speaker": teacher, "text": f"{pickup_label}下午会来接你，现在我们先去看看桌上的材料。"},
                {"speaker": child.name, "text": temperament_line},
                {"speaker": peer, "text": "你要不要和我一起搭这个？"},
                {"speaker": child.name, "text": "我拿蓝色的，可以吗？"},
                {"speaker": peer, "text": "可以，我拿红色的。"},
                {"speaker": child.name, "text": "这个高高的，不要倒。"},
                {"speaker": teacher, "text": "你们可以一人放一个，慢慢来。"},
                {"speaker": child.name, "text": event_line},
                {"speaker": teacher, "text": "等会儿收材料时，我会再提醒一次。"},
                {"speaker": child.name, "text": "我可以把蓝色的放回盒子里。"},
            ]
        elif schedule["scene"] == "community":
            scene_description = f"{place}里，{child.name}和{caregiver}边走边看，把户外发现说出来。"
            dialogue = [
                {"speaker": caregiver, "text": "我们走慢一点，看路边有什么变化。"},
                {"speaker": child.name, "text": f"{caregiver}，这里有一片小叶子。"},
                {"speaker": caregiver, "text": "你可以蹲下来看看，不要离开我太远。"},
                {"speaker": child.name, "text": "它有一点弯弯的。"},
                {"speaker": caregiver, "text": "你发现了形状。还想看哪里？"},
                {"speaker": child.name, "text": temperament_line},
                {"speaker": child.name, "text": "我想摸一下这个石头。"},
                {"speaker": caregiver, "text": "可以，用手指轻轻碰一下。"},
                {"speaker": child.name, "text": "凉凉的。"},
                {"speaker": caregiver, "text": "那我们把手擦一擦。"},
                {"speaker": child.name, "text": event_line},
                {"speaker": caregiver, "text": "你可以告诉我刚才最喜欢什么。"},
                {"speaker": child.name, "text": "我喜欢那个小叶子。"},
                {"speaker": caregiver, "text": "好，回家后你可以画给我看。"},
            ]
        else:
            scene_description = f"{place}里，{child.name}和{caregiver}围绕{focus}慢慢收束半天节奏。"
            dialogue = [
                {"speaker": caregiver, "text": "我们先把桌上的东西收一收。"},
                {"speaker": child.name, "text": f"{caregiver}，这个是我刚才玩的。"},
                {"speaker": caregiver, "text": "我看见了，你可以先放回盒子。"},
                {"speaker": child.name, "text": "我要放蓝色的。"},
                {"speaker": caregiver, "text": "可以，蓝色的先进去。"},
                {"speaker": child.name, "text": temperament_line},
                {"speaker": other_family, "text": "放完以后我们去洗手。"},
                {"speaker": child.name, "text": "我自己拿毛巾。"},
                {"speaker": caregiver, "text": "好，我在旁边等你。"},
                {"speaker": child.name, "text": "我还差一个。"},
                {"speaker": caregiver, "text": "最后一个放好就完成了。"},
                {"speaker": child.name, "text": event_line},
                {"speaker": other_family, "text": "那我们一起检查一下。"},
                {"speaker": child.name, "text": "都放好了，我要去洗手。"},
            ]

        if interventions:
            guide_speaker = self._first_actor_label(involved_actors, str((intervention_plan or {}).get("target_role") or "")) or (caregiver if schedule["scene"] != "kindergarten" else teacher)
            dialogue[-2] = {"speaker": guide_speaker, "text": f"今天我们按“{guided_style}”来，先一起试试{guided_goal}。"}
        return {
            "scene_description": scene_description,
            "dialogue": dialogue[:20],
            "participants": [child.name, *[str(actor.get("display_label") or actor.get("name")) for actor in involved_actors if actor.get("display_label") or actor.get("name")]][:5],
        }

    def _temperament_child_line(self, child: SimAgent) -> str:
        temperament = str((child.traits or {}).get("temperament_baseline") or "")
        if "敏感" in temperament or "慢热" in temperament:
            return "我先看一下，再放进去。"
        if "活泼" in temperament or "运动" in temperament:
            return "我想快一点，还想再来一次。"
        if "安静" in temperament or "专注" in temperament:
            return "我想把这个放整齐。"
        return "我自己试试看。"

    def _normalize_life_slice(self, value: Any, fallback: dict[str, Any], *, child: SimAgent, involved_actors: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(value, dict):
            return fallback
        scene_description = str(value.get("scene_description") or value.get("scene") or "").strip()
        raw_dialogue = value.get("dialogue")
        if not scene_description or not isinstance(raw_dialogue, list):
            return fallback
        dialogue: list[dict[str, str]] = []
        for item in raw_dialogue:
            speaker = ""
            text = ""
            if isinstance(item, dict):
                speaker = str(item.get("speaker") or item.get("role") or "").strip()
                text = str(item.get("text") or item.get("line") or item.get("content") or "").strip()
            elif isinstance(item, str) and "：" in item:
                speaker, text = [part.strip() for part in item.split("：", 1)]
            if speaker and text:
                dialogue.append(
                    {
                        "speaker": self._replace_generic_caregiver(speaker, child=child, involved_actors=involved_actors),
                        "text": self._replace_generic_caregiver(text, child=child, involved_actors=involved_actors),
                    }
                )
        if len(dialogue) < 10:
            return fallback
        return {
            "scene_description": self._replace_generic_caregiver(scene_description, child=child, involved_actors=involved_actors),
            "dialogue": dialogue[:20],
            "participants": value.get("participants") if isinstance(value.get("participants"), list) else fallback.get("participants", []),
        }

    def _fallback_gm_interpretation(
        self,
        *,
        schedule: dict[str, Any],
        random_event: RandomEventTemplate | None,
        interventions: list[dict[str, Any]],
        involved_relationships: list[AgentRelationship],
        involved_actors: list[dict[str, Any]],
        intervention_plan: dict[str, Any] | None,
    ) -> str:
        domain_labels = [DEVELOPMENT_DOMAINS.get(key, key) for key in schedule.get("domains", [])]
        relationship_roles = sorted({relationship.relationship_type for relationship in involved_relationships})
        role_labels = {"caregiver": "家庭成人", "teacher": "老师", "peer": "同伴"}
        relationship_text = self._actor_text(involved_actors, fallback="、".join(role_labels.get(role, role) for role in relationship_roles) or "当前场景关系")
        parts = [
            f"本地 GM 将这半天解释为一次{schedule['main']}相关的日常经历，主要提供{', '.join(domain_labels)}的证据。",
            f"关系层面重点观察{relationship_text}互动，先记录证据，不直接做大幅关系或发展分数调整。",
        ]
        if random_event is not None:
            parts.append(f"随机事件“{random_event.name}”被按温和事件处理，只扩大观察线索，不生成高风险叙事。")
        if interventions:
            parts.append("观察者干预被视为环境条件变化，不能直接改儿童状态。")
        if intervention_plan and intervention_plan.get("activity_goal"):
            parts.append(f"本步优先把活动组织到“{intervention_plan['activity_goal']}”，作为下一步环境引导而非直接状态修改。")
        return " ".join(parts)

    def _fallback_state_update_evidence(
        self,
        *,
        schedule: dict[str, Any],
        location: WorldLocation | None,
        sub_fragments: list[str],
        random_event: RandomEventTemplate | None,
        interventions: list[dict[str, Any]],
        involved_relationships: list[AgentRelationship],
        intervention_plan: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = [
            {
                "source": "half_day_schedule",
                "detail": f"{location.name if location else schedule['scene']}场景触发半天 needs 节律更新。",
                "domains": schedule.get("domains", []),
            },
            {
                "source": "observed_fragments",
                "detail": "；".join(sub_fragments) if sub_fragments else schedule["main"],
                "domains": schedule.get("domains", []),
            },
        ]
        if involved_relationships:
            evidence.append(
                {
                    "source": "relationship_interaction",
                    "detail": "本半天参与关系边提供 familiarity/warmth/trust/tension 的结算证据。",
                    "relationship_ids": [relationship.id for relationship in involved_relationships],
                }
            )
        if random_event is not None:
            evidence.append({"source": "random_event", "detail": random_event.name, "severity": random_event.severity})
        if interventions:
            evidence.append({"source": "observer_intervention", "detail": safe_memory_text(interventions[0].get("text"))})
        if intervention_plan:
            plan_evidence = {
                "source": "intervention_plan",
                "detail": self._intervention_effect_summary(intervention_plan, []),
                "activity_goal": intervention_plan.get("activity_goal"),
                "guidance_style": intervention_plan.get("guidance_style"),
                "target_role": intervention_plan.get("target_role"),
            }
            return [*evidence[:4], plan_evidence]
        return evidence[:5]

    def _fallback_suggested_updates(self, *, schedule: dict[str, Any], involved_relationships: list[AgentRelationship]) -> dict[str, Any]:
        return {
            "development_evidence": [
                {"domain": domain, "direction": "evidence_only", "reason": "半天活动提供观察证据，分数等待 14 step 结算。"}
                for domain in schedule.get("domains", [])
            ],
            "relationship_evidence": [
                {"relationship_id": relationship.id, "type": relationship.relationship_type, "direction": "evidence_only"}
                for relationship in involved_relationships
            ],
            "needs_policy": {"mode": "rhythm_clamped", "scene": schedule["scene"]},
        }

    def _important_memory_writes(
        self,
        *,
        child: SimAgent,
        outcome: dict[str, Any],
        random_event: RandomEventTemplate | None,
        interventions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        writes: list[dict[str, Any]] = []
        if random_event is not None:
            writes.append(
                {
                    "agent_id": child.id,
                    "content": f"{child.name}经历了温和随机事件“{random_event.name}”：{outcome['half_day_summary']}",
                    "memory_type": "event",
                    "confidence": 0.72,
                    "importance": "medium",
                }
            )
        for intervention in interventions[:1]:
            writes.append(
                {
                    "agent_id": child.id,
                    "content": f"观察者干预影响了{child.name}的半天经历：{safe_memory_text(intervention.get('text'))}",
                    "memory_type": "event",
                    "confidence": 0.76,
                    "importance": "high",
                }
            )
        return writes

    def _sub_fragments(
        self,
        schedule: dict[str, Any],
        random_event: RandomEventTemplate | None,
        involved_actors: list[dict[str, Any]] | None = None,
        intervention_plan: dict[str, Any] | None = None,
    ) -> list[str]:
        actors = involved_actors or []
        home_actor = self._actor_text(self._actors_by_type(actors, "caregiver"), fallback="熟悉成人")
        school_actor = self._actor_text(actors, fallback="老师和同伴")
        community_actor = self._actor_text(actors, fallback="身边成人")
        activity_goal = str((intervention_plan or {}).get("activity_goal") or "").strip()
        guidance_style = str((intervention_plan or {}).get("guidance_style") or "").strip()
        fragments = {
            "kindergarten": [f"入园时和{school_actor}确认接送安排", "参与一次集体或自由游戏", "在老师提示下整理材料"],
            "home": [f"和{home_actor}完成生活过渡", "进行一段自由玩耍或交流", "练习整理和自理步骤"],
            "community": ["观察户外环境", "尝试一种身体活动", f"和{community_actor}分享发现"],
        }.get(schedule["scene"], ["完成半天日常活动"])
        if activity_goal:
            fragments[1 if len(fragments) > 1 else 0] = f"在{self._actor_text(actors)}支持下参与{activity_goal}"
        if guidance_style and len(fragments) > 2:
            fragments[2] = f"使用{guidance_style}完成活动过渡"
        if random_event is not None:
            fragments = [*fragments[:2], random_event.name]
        return fragments[:3]

    def _child_voice(self, child: SimAgent, schedule: dict[str, Any], random_event: RandomEventTemplate | None, *, involved_actors: list[dict[str, Any]], tick_no: int) -> str:
        suffix = "，有一点不一样。" if random_event else "。"
        family_labels = self._family_labels(child)
        home_label = self._first_actor_label(involved_actors, "caregiver") or (family_labels[0] if family_labels else "大人")
        community_label = self._first_actor_label(involved_actors) or home_label
        if schedule["scene"] == "kindergarten":
            variants = [
                f"我进幼儿园的时候有点看大人，后来跟着大家玩了一会儿{suffix}",
                f"老师说下一步做什么，我试着听懂，也和小朋友待在一起{suffix}",
                f"我在幼儿园做了几件事，有时候想自己玩，有时候也看看别人{suffix}",
            ]
            return variants[(tick_no - 1) % len(variants)]
        if schedule["scene"] == "community":
            variants = [
                f"我在外面看到了新东西，想告诉{community_label}{suffix}",
                f"外面的东西有点多，我一边走一边看{suffix}",
                f"我想摸一摸、看一看，再跟{community_label}说我发现了什么{suffix}",
            ]
            return variants[(tick_no - 1) % len(variants)]
        variants = [
            f"我回到熟悉的地方，慢慢把事情做完{suffix}",
            f"在家里我比较知道接下来要做什么，也想让{home_label}陪一下{suffix}",
            f"我有点累了，但熟悉的人在旁边，我可以一点一点整理好{suffix}",
        ]
        return variants[(tick_no - 1) % len(variants)]

    def _apply_child_state(self, state: AgentState, *, child: SimAgent, location: WorldLocation | None, outcome: dict[str, Any], tick_no: int) -> None:
        child.current_location_id = location.id if location is not None else child.current_location_id
        state.current_action = outcome["main_action"]
        state.mood = "curious" if "新" in outcome["child_interpretation"] else "calm"
        needs = self._updated_needs(state.needs or default_needs(), scene=location.kind if location else "home", half_index=(tick_no - 1) % 2)
        metadata = dict(state.metadata_ or {})
        development = self._updated_development(metadata.get("development") or default_development(child.traits.get("age_months", 48)), outcome=outcome, tick_no=tick_no)
        if tick_no % 14 == 0:
            development = self._settle_development(development)
        summaries = list(metadata.get("half_day_summaries") or [])
        summaries.append(
            {
                "tick_no": tick_no,
                "summary": outcome["half_day_summary"],
                "child_interpretation": outcome["child_interpretation"],
                "life_slice": outcome["life_slice"],
            }
        )
        metadata["half_day_summaries"] = summaries[-28:]
        metadata["development"] = development
        if outcome["memory_writes"]:
            key_memories = list(metadata.get("key_memories") or [])
            for item in outcome["memory_writes"][:2]:
                if isinstance(item, dict) and item.get("content"):
                    key_memories.append({"tick_no": tick_no, "content": str(item["content"]), "importance": item.get("importance", "medium")})
            metadata["key_memories"] = key_memories[-20:]
        state.needs = needs
        state.metadata_ = metadata

    def _updated_needs(self, needs: dict[str, Any], *, scene: str, half_index: int) -> dict[str, int]:
        current = {key: clamp(needs.get(key, default_needs()[key])) for key in NEED_KEYS}
        if scene == "kindergarten":
            delta = {"energy": -12, "satiety": -8, "sleep_quality": 0, "health": 0, "hygiene": -6, "safety": -2, "stress": 6}
        elif scene == "community":
            delta = {"energy": -10, "satiety": -6, "sleep_quality": 0, "health": 0, "hygiene": -8, "safety": 2, "stress": 2}
        else:
            delta = {"energy": 6 if half_index == 1 else -4, "satiety": 8, "sleep_quality": 4 if half_index == 1 else 0, "health": 0, "hygiene": 6, "safety": 5, "stress": -5}
        return {key: clamp(current[key] + delta[key]) for key in NEED_KEYS}

    def _updated_development(self, development: dict[str, Any], *, outcome: dict[str, Any], tick_no: int) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        text = " ".join([outcome["half_day_summary"], *outcome["observed_facts"], outcome["gm_interpretation"]])
        for key, label in DEVELOPMENT_DOMAINS.items():
            row = development.get(key) if isinstance(development.get(key), dict) else {}
            buffer = list(row.get("evidence_buffer") or [])
            impact = 0.15
            if label[:2] in text or key in str(outcome.get("suggested_updates")):
                impact = 0.35
            if "冲突" in text and key in {"emotional_regulation", "social_cooperation"}:
                impact = 0.2
            buffer.append({"tick_no": tick_no, "label": label, "impact": impact, "evidence": outcome["half_day_summary"]})
            normalized[key] = {
                "score": clamp(row.get("score", 50)),
                "trend": str(row.get("trend") or "stable"),
                "evidence_buffer": buffer[-14:],
                "confidence": max(0, min(1, float(row.get("confidence") or 0.55))),
            }
        return normalized

    def _settle_development(self, development: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        settled: dict[str, dict[str, Any]] = {}
        for key, row in development.items():
            evidence = row.get("evidence_buffer") or []
            total = sum(float(item.get("impact") or 0) for item in evidence if isinstance(item, dict))
            score = clamp(row.get("score", 50))
            raw_delta = 1 if total >= 2.6 else (-1 if total <= -1.0 else 0)
            if score >= 82 and raw_delta > 0:
                raw_delta = 0
            if score <= 35 and raw_delta < 0:
                raw_delta = 0
            new_score = clamp(score + raw_delta)
            settled[key] = {
                **row,
                "score": new_score,
                "trend": "up" if raw_delta > 0 else ("down" if raw_delta < 0 else "stable"),
                "evidence_buffer": [],
                "confidence": max(0.55, min(0.95, float(row.get("confidence") or 0.55) + 0.02)),
                "last_settlement_delta": raw_delta,
            }
        return settled

    def _apply_relationship_evidence(
        self,
        relationships: list[AgentRelationship],
        *,
        outcome: dict[str, Any],
        tick_no: int,
    ) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for relationship in relationships:
            metrics = dict(relationship.metrics or {})
            evidence = list(relationship.evidence_buffer or [])
            familiarity_delta = 1
            metrics["familiarity"] = clamp(metrics.get("familiarity", 50) + familiarity_delta)
            evidence.append({"tick_no": tick_no, "summary": outcome["half_day_summary"], "impact": 0.4})
            if tick_no % 14 == 0:
                metrics, settled = self._settle_relationship(metrics, evidence, relationship.relationship_type)
                evidence = []
            else:
                settled = {}
            relationship.metrics = metrics
            relationship.evidence_buffer = evidence[-14:]
            relationship.last_summary = outcome["half_day_summary"]
            changes.append({"relationship_id": relationship.id, "npc_agent_id": relationship.npc_agent_id, "metrics": metrics, "settlement": settled})
        return changes

    def _settle_relationship(self, metrics: dict[str, Any], evidence: list[Any], relationship_type: str) -> tuple[dict[str, int], dict[str, int]]:
        evidence_count = len(evidence)
        delta = 2 if evidence_count >= 5 else 1
        settled = {"familiarity": min(2, delta)}
        updated = {key: clamp(value) for key, value in metrics.items() if isinstance(value, int | float)}
        for key in ("warmth", "trust_security"):
            settled[key] = min(2, max(0, delta - 1))
            updated[key] = clamp(updated.get(key, 50) + settled[key])
        updated["tension"] = clamp(updated.get("tension", 10) - 1)
        for key in ROLE_EXTRA_METRICS.get(relationship_type, ()):
            settled[key] = min(2, max(0, delta - 1))
            updated[key] = clamp(updated.get(key, 50) + settled[key])
        return updated, settled

    async def _maybe_generate_report(
        self,
        session: AsyncSession,
        *,
        world: SimulationWorld,
        child: SimAgent,
        state: AgentState,
        relationships: list[AgentRelationship],
        tick_no: int,
        source_event: SimulationEvent,
    ) -> SimulationEvent | None:
        if tick_no % 14 != 0:
            return None
        period_start = tick_no - 13
        events = (
            await session.execute(
                select(SimulationEvent)
                .where(SimulationEvent.world_id == world.id, SimulationEvent.tick_no >= period_start, SimulationEvent.tick_no <= tick_no)
                .order_by(SimulationEvent.tick_no)
            )
        ).scalars().all()
        report_payload = {
            "major_experiences": [event.payload.get("half_day_summary") or event.payload.get("summary") for event in events if event.payload.get("half_day_summary") or event.payload.get("summary")][-6:],
            "emotional_patterns": "本周以温和日常适应为主，压力和安全感随场景转换小幅波动。",
            "development_trends": {
                key: {"label": DEVELOPMENT_DOMAINS[key], "score": row.get("score"), "trend": row.get("trend"), "delta": row.get("last_settlement_delta", 0)}
                for key, row in (state.metadata_.get("development") or {}).items()
                if key in DEVELOPMENT_DOMAINS
            },
            "relationship_changes": [
                {"npc_agent_id": relationship.npc_agent_id, "relationship_type": relationship.relationship_type, "metrics": relationship.metrics}
                for relationship in relationships
            ],
            "key_memories": state.metadata_.get("key_memories", [])[-5:],
            "intervention_effects": [event.payload.get("summary") for event in events if event.payload.get("interventions")],
            "next_week_focus": ["继续观察入园/分离过渡", "关注同伴合作中的情绪调节", "保留稳定睡前和整理节奏"],
            "disclaimer": "本报告只用于虚构成长模拟，不构成医学、心理或现实育儿诊断建议。",
        }
        report = GrowthReport(
            world_id=world.id,
            child_agent_id=child.id,
            period_start_tick=period_start,
            period_end_tick=tick_no,
            report=report_payload,
        )
        session.add(report)
        await session.flush()
        event = SimulationEvent(
            world_id=world.id,
            tick_no=tick_no,
            event_type="growth_report",
            source="child_growth",
            status="completed",
            reference_time=source_event.reference_time,
            actors=[child.id],
            location_id=child.current_location_id,
            payload={"world_id": world.id, "summary": "生成 7 天成长报告。", "growth_report_id": report.id, "report": report_payload},
        )
        session.add(event)
        await session.flush()
        report.source_event_id = event.id
        return event

    async def _persist_memory(self, session: AsyncSession, event: SimulationEvent) -> None:
        try:
            await self.memory_writer.persist_event(session, simulation_event=event)
        except Exception:
            await session.flush()

    async def _snapshot(self, session: AsyncSession, *, world: SimulationWorld, child: SimAgent, event_cursor: str | None) -> None:
        relationships = (
            await session.execute(select(AgentRelationship).where(AgentRelationship.world_id == world.id, AgentRelationship.child_agent_id == child.id))
        ).scalars().all()
        state = {
            "world": {"id": world.id, "tick_no": world.tick_no, "clock_time": world.clock_time.isoformat(), "world_type": WORLD_TYPE},
            "child": {
                "id": child.id,
                "name": child.name,
                "current_location_id": child.current_location_id,
                "needs": child.state.needs if child.state else {},
                "metadata": child.state.metadata_ if child.state else {},
            },
            "relationships": [
                {"id": relationship.id, "npc_agent_id": relationship.npc_agent_id, "relationship_type": relationship.relationship_type, "metrics": relationship.metrics}
                for relationship in relationships
            ],
            "event_cursor": event_cursor,
        }
        session.add(WorldSnapshot(world_id=world.id, tick_no=world.tick_no, clock_time=world.clock_time, state=state, event_cursor=event_cursor))


def branch_preview(world_id: str, snapshot_id: str | None) -> BranchPreviewResponse:
    return BranchPreviewResponse(
        world_id=world_id,
        requested_snapshot_id=snapshot_id,
        data_shape={
            "base_snapshot_id": snapshot_id,
            "branch_label": "future_placeholder",
            "would_compare": ["development", "relationships", "events", "needs"],
        },
    )


async def maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
