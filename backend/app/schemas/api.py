from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PersonaType = Literal["fictional_persona", "authorized_real_persona"]
Decision = Literal["pending", "approved", "rejected"]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class AdminUserResponse(BaseModel):
    username: str
    role: str = "admin"


class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    persona_type: PersonaType = "fictional_persona"
    consent_confirmed: bool = False
    persona_block: str = ""
    human_block: str = ""


class PersonaGenerateRequest(BaseModel):
    description: str = Field(min_length=1)
    memory_count: int = Field(default=8, ge=4, le=12)


class GeneratedMemoryDraft(BaseModel):
    content: str = Field(min_length=1)
    memory_type: str = "fact"
    confidence: float = Field(default=0.75, ge=0, le=1)


class PersonaGenerateResponse(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1)
    persona_block: str = Field(min_length=1)
    human_block: str = Field(min_length=1)
    memories: list[GeneratedMemoryDraft] = Field(default_factory=list)


class GeneratedPersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1)
    persona_block: str = Field(min_length=1)
    human_block: str = Field(min_length=1)
    memories: list[GeneratedMemoryDraft] = Field(default_factory=list)


class PersonaUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    consent_confirmed: bool | None = None
    persona_block: str | None = None
    human_block: str | None = None
    status: str | None = None


class PersonaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    persona_type: str
    consent_confirmed: bool
    persona_block: str
    human_block: str
    letta_agent_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class CoreMemoryResponse(BaseModel):
    persona_id: str
    persona_block: str
    human_block: str
    letta_agent_id: str | None
    proposals: list["CoreMemoryProposalResponse"] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    persona_id: str
    counterparty_user_id: str = "default-human"
    title: str = "新的对话"
    channel: str = "web"


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    persona_id: str
    counterparty_user_id: str
    title: str
    channel: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    context: dict[str, Any]
    created_at: datetime


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse] = Field(default_factory=list)


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1)
    reference_time: datetime | None = None


class SourceRef(BaseModel):
    source_type: str
    source_id: str | None = None
    event_id: str | None = None
    timestamp: datetime | None = None
    provenance: str = ""


class EvidenceItem(BaseModel):
    source: str
    content: str
    score: float | None = None
    source_ref: SourceRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConflictNote(BaseModel):
    claim: str
    status: str
    current_best_view: str
    supporting_evidence: list[EvidenceItem] = Field(default_factory=list)


class ContextBundle(BaseModel):
    core_persona: str
    current_human_relationship: str
    long_term_memories: list[EvidenceItem] = Field(default_factory=list)
    temporal_facts: list[EvidenceItem] = Field(default_factory=list)
    document_evidence: list[EvidenceItem] = Field(default_factory=list)
    conflict_notes: list[ConflictNote] = Field(default_factory=list)
    route: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    user_message: MessageResponse
    assistant_message: MessageResponse
    context_bundle: ContextBundle


class MemorySearchRequest(BaseModel):
    query: str
    persona_id: str
    counterparty_user_id: str | None = None
    k: int = 8


class MemoryRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    persona_id: str
    counterparty_user_id: str | None
    scope: str
    subject: str
    memory_type: str
    content: str
    confidence: float
    sensitivity: str
    decision: str
    source_event_id: str | None
    external_id: str | None
    created_at: datetime
    updated_at: datetime


class MemoryCandidate(BaseModel):
    content: str
    subject: str
    memory_type: str = "fact"
    confidence: float = 0.7
    source_event_id: str | None = None
    sensitivity: str = "normal"
    decision: Decision = "pending"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TimelineSearchRequest(BaseModel):
    query: str
    time_range: tuple[datetime, datetime] | None = None
    k: int = 8


class CorpusCreate(BaseModel):
    persona_id: str
    name: str
    corpus_type: str = "background"
    description: str = ""


class CorpusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    persona_id: str
    name: str
    corpus_type: str
    description: str
    created_at: datetime
    updated_at: datetime


class DocumentCreate(BaseModel):
    filename: str
    raw_text: str
    content_type: str = "text/plain"


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    corpus_id: str
    persona_id: str
    filename: str
    content_type: str
    status: str
    external_id: str | None
    error: str
    created_at: datetime
    updated_at: datetime


class DocumentSearchRequest(BaseModel):
    query: str
    persona_id: str
    corpus_ids: list[str] | None = None
    mode: str = "hybrid"
    k: int = 5


class CoreMemoryProposalCreate(BaseModel):
    target_block: Literal["persona", "human"]
    operation: str = "update"
    old_text: str = ""
    new_text: str
    reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.7


class CoreMemoryProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    persona_id: str
    target_block: str
    operation: str
    old_text: str
    new_text: str
    reason: str
    evidence_ids: list[str]
    confidence: float
    status: str
    created_at: datetime
    updated_at: datetime


class EvalRunRequest(BaseModel):
    persona_id: str | None = None


class EvalRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    persona_id: str | None
    status: str
    results: dict[str, Any]
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    services: dict[str, Any]


class ToolBuildContextRequest(BaseModel):
    query: str
    persona_id: str
    counterparty_user_id: str | None = None
    conversation_id: str | None = None


class SimulationWorldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    clock_time: datetime | None = None
    speed: float = Field(default=1.0, ge=0)
    seed: int = 1
    settings: dict[str, Any] = Field(default_factory=dict)


class ChildWorldDraftRequest(BaseModel):
    template_key: str = Field(default="curious_outgoing", max_length=80)
    child_name: str | None = Field(default=None, max_length=160)
    age_months: int = Field(default=48, ge=36, le=72)
    caregiver_1_label: str = Field(default="照护者一", max_length=40)
    caregiver_2_label: str = Field(default="照护者二", max_length=40)
    kindergarten_class: str = Field(default="幼儿园混龄班", max_length=80)
    peer_count: int = Field(default=2, ge=2, le=4)
    natural_language_prompt: str = ""
    seed: int | None = None


class ChildWorldDraftConfirm(BaseModel):
    parsed_draft: dict[str, Any] | None = None
    world_name: str | None = Field(default=None, max_length=180)
    seed: int | None = None
    start_running: bool = False


class ChildWorldDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    template_key: str
    input_params: dict[str, Any]
    natural_language_prompt: str
    raw_response: str
    parsed_draft: dict[str, Any]
    risk_flags: list[Any]
    created_world_id: str | None
    created_at: datetime
    updated_at: datetime


class SimulationWorldUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    status: str | None = None
    speed: float | None = Field(default=None, ge=0)
    settings: dict[str, Any] | None = None


class SimulationWorldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    clock_time: datetime
    speed: float
    seed: int
    tick_no: int
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WorldLocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    kind: str = "place"
    x: float = 0.0
    y: float = 0.0
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldLocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    world_id: str
    name: str
    kind: str
    x: float
    y: float
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class CommunityRuleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1)
    priority: int = 100
    status: str = "active"
    effective_from: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommunityRuleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    content: str | None = Field(default=None, min_length=1)
    priority: int | None = None
    status: str | None = None
    effective_from: datetime | None = None
    metadata: dict[str, Any] | None = None


class CommunityRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    world_id: str
    title: str
    content: str
    priority: int
    status: str
    effective_from: datetime | None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class SimAgentCreate(BaseModel):
    persona_id: str
    name: str | None = Field(default=None, max_length=180)
    status: str = "active"
    home_location_id: str | None = None
    current_location_id: str | None = None
    goals: dict[str, Any] = Field(default_factory=dict)
    traits: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimAgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    status: str | None = None
    home_location_id: str | None = None
    current_location_id: str | None = None
    goals: dict[str, Any] | None = None
    traits: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class AgentStateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    agent_id: str
    needs: dict[str, Any]
    mood: str
    plan: dict[str, Any]
    current_action: str
    cooldowns: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")


class AgentRelationshipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    world_id: str
    child_agent_id: str
    npc_agent_id: str
    relationship_type: str
    metrics: dict[str, Any]
    evidence_buffer: list[Any]
    confidence: float
    last_summary: str
    created_at: datetime
    updated_at: datetime


class SimAgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    world_id: str
    persona_id: str
    name: str
    status: str
    home_location_id: str | None
    current_location_id: str | None
    goals: dict[str, Any]
    traits: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    state: AgentStateResponse | None = None
    created_at: datetime
    updated_at: datetime


class RandomEventTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    trigger: dict[str, Any] = Field(default_factory=dict)
    probability: float = Field(default=0.1, ge=0, le=1)
    cooldown: int = Field(default=0, ge=0)
    severity: str = "info"
    effect_prompt: str = ""
    status: str = "active"


class RandomEventTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    trigger: dict[str, Any] | None = None
    probability: float | None = Field(default=None, ge=0, le=1)
    cooldown: int | None = Field(default=None, ge=0)
    severity: str | None = None
    effect_prompt: str | None = None
    status: str | None = None


class RandomEventTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    world_id: str
    name: str
    trigger: dict[str, Any]
    probability: float
    cooldown: int
    severity: str
    effect_prompt: str
    status: str
    last_triggered_at: datetime | None
    last_triggered_event_id: str | None
    created_at: datetime
    updated_at: datetime


class UserInterventionCreate(BaseModel):
    actor: str = "admin"
    intervention_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)


class UserInterventionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    world_id: str
    actor: str
    intervention_type: str
    payload: dict[str, Any]
    status: str
    result_event_id: str | None
    created_at: datetime
    updated_at: datetime


class SimulationEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    world_id: str
    tick_no: int
    event_type: str
    source: str
    status: str
    reference_time: datetime
    actors: list[Any]
    location_id: str | None
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class GrowthReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    world_id: str
    child_agent_id: str
    period_start_tick: int
    period_end_tick: int
    report: dict[str, Any]
    source_event_id: str | None
    created_at: datetime
    updated_at: datetime


class WorldSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    world_id: str
    tick_no: int
    clock_time: datetime
    state: dict[str, Any]
    event_cursor: str | None
    created_at: datetime
    updated_at: datetime


class AgentProjection(BaseModel):
    id: str
    persona_id: str
    name: str
    status: str
    current_location_id: str | None
    home_location_id: str | None
    current_action: str = ""
    mood: str = "neutral"
    goals: dict[str, Any] = Field(default_factory=dict)
    traits: dict[str, Any] = Field(default_factory=dict)


class ChildProjection(BaseModel):
    agent: SimAgentResponse
    location: WorldLocationResponse | None = None
    needs: dict[str, Any] = Field(default_factory=dict)
    development: dict[str, Any] = Field(default_factory=dict)
    key_memories: list[Any] = Field(default_factory=list)
    half_day_summaries: list[Any] = Field(default_factory=list)


class BranchPreviewResponse(BaseModel):
    world_id: str
    available: bool = False
    message: str = "分支对比接口已预留，MVP 不运行真实分支。"
    requested_snapshot_id: str | None = None
    data_shape: dict[str, Any] = Field(default_factory=dict)


class BranchPreviewRequest(BaseModel):
    snapshot_id: str | None = None
    label: str | None = Field(default=None, max_length=120)


class WorldStateProjection(BaseModel):
    world: SimulationWorldResponse
    locations: list[WorldLocationResponse] = Field(default_factory=list)
    agents: list[AgentProjection] = Field(default_factory=list)
    rules: list[CommunityRuleResponse] = Field(default_factory=list)
    recent_events: list[SimulationEventResponse] = Field(default_factory=list)
    child: ChildProjection | None = None
    relationships: list[AgentRelationshipResponse] = Field(default_factory=list)
    growth_reports: list[GrowthReportResponse] = Field(default_factory=list)
    snapshots: list[WorldSnapshotResponse] = Field(default_factory=list)
    branch_preview: BranchPreviewResponse | None = None


class SimulationStepResponse(BaseModel):
    world: SimulationWorldResponse
    events: list[SimulationEventResponse]
    state: WorldStateProjection
