from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

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
    source_observation_draft_id: str | None = Field(default=None, max_length=36)


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


class ChildObservationStructuredSetup(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    template_key: str = Field(default="curious_outgoing", max_length=80)
    child_display_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("child_display_name", "child_name"),
        max_length=160,
    )
    age_months: int = Field(default=48, ge=36, le=72)
    caregiver_1_label: str = Field(default="照护者一", max_length=40)
    caregiver_2_label: str = Field(default="照护者二", max_length=40)
    kindergarten_class: str = Field(default="幼儿园混龄班", max_length=80)
    peer_count: int = Field(default=2, ge=2, le=4)
    natural_language_prompt: str = ""
    seed: int | None = None

    def to_child_world_request(self, prompt: str | None = None, source_observation_draft_id: str | None = None) -> ChildWorldDraftRequest:
        return ChildWorldDraftRequest(
            template_key=self.template_key,
            child_name=self.child_display_name,
            age_months=self.age_months,
            caregiver_1_label=self.caregiver_1_label,
            caregiver_2_label=self.caregiver_2_label,
            kindergarten_class=self.kindergarten_class,
            peer_count=self.peer_count,
            natural_language_prompt=prompt if prompt is not None else self.natural_language_prompt,
            seed=self.seed,
            source_observation_draft_id=source_observation_draft_id,
        )


class MediaAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    owner_actor: str
    original_filename: str
    media_type: str
    mime_type: str
    sha256: str
    size_bytes: int
    duration_seconds: float | None
    width: int | None
    height: int | None
    preview_refs: list[Any]
    preview_retention: str = "review_only_delete_with_raw"
    status: str
    privacy_flags: list[Any]
    deletion_reason: str
    deleted_at: datetime | None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class MediaUploadResponse(BaseModel):
    assets: list[MediaAssetResponse]
    errors: list[dict[str, Any]] = Field(default_factory=list)


class AssetStates(BaseModel):
    analyzed: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)


class TargetChildDescriptor(BaseModel):
    description: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list)
    operator_confirmed: bool = False
    operator_override: str | None = None
    confidence_band: str = "low"


class ChildObservationAnalysisJobCreate(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)
    structured_setup: ChildObservationStructuredSetup
    target_child_hint: dict[str, Any] | None = None
    include_audio: bool = True


class MediaAnalysisJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    phase: str = ""
    asset_states: AssetStates
    asset_progress: dict[str, Any] = Field(default_factory=dict)
    frame_progress: dict[str, int] = Field(default_factory=lambda: {"total": 0, "analyzed": 0, "failed": 0, "pending": 0})
    target_child: dict[str, Any]
    observation_draft_id: str | None = None
    error_message: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ObservationReviewItem(BaseModel):
    item_path: str = Field(min_length=1, max_length=240)
    decision: Literal["approved", "edited", "rejected", "downgraded", "unknown"]
    final_value: dict[str, Any] | str | None = None
    rationale: str = ""


class TargetChildConfirmation(BaseModel):
    confirmed: bool = False
    operator_override: str | None = Field(default=None, max_length=400)


class AuthorizationConfirmation(BaseModel):
    confirmed: bool = False
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    authorization_scope: list[str] = Field(default_factory=list)
    risk_categories: list[str] = Field(default_factory=list)
    operator_rationale: str = ""
    retained_content_scope: str = ""


class ObservationDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    analysis_job_id: str
    child_world_draft_id: str | None
    structured_setup: dict[str, Any]
    target_child: dict[str, Any]
    observable_summary: str
    visible_observations: list[Any]
    generated_child_description: str = ""
    accepted_child_description: str = ""
    audio_observations: list[Any]
    non_identifying_appearance: list[Any]
    behavior_signals: list[Any]
    temperament_hypotheses: list[Any]
    interests: list[Any]
    development_hints: dict[str, Any]
    avatar_brief: dict[str, Any]
    initial_memory_candidates: list[Any]
    unknowns: list[Any]
    risk_flags: list[Any]
    authorization_confirmation: dict[str, Any]
    approved_payload: dict[str, Any]
    raw_media_deleted_at: datetime | None
    asset_states: AssetStates | None = None
    preview_refs: list[Any] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ObservationReviewRequest(BaseModel):
    target_child_confirmation: TargetChildConfirmation = Field(default_factory=TargetChildConfirmation)
    decisions: list[ObservationReviewItem] = Field(default_factory=list)
    authorization_confirmation: AuthorizationConfirmation = Field(default_factory=AuthorizationConfirmation)


class ObservationReviewResponse(BaseModel):
    id: str
    status: str
    approved_payload: dict[str, Any]
    raw_media_deleted: bool
    raw_media_deletion_pending: bool = False


class ObservationDescriptionAcceptRequest(BaseModel):
    description: str = Field(min_length=1, max_length=6000)
    authorization_confirmation: AuthorizationConfirmation = Field(default_factory=AuthorizationConfirmation)


class ObservationDescriptionAcceptResponse(BaseModel):
    id: str
    status: str
    accepted_child_description: str
    raw_media_deleted: bool
    risk_flags: list[Any] = Field(default_factory=list)


class ObservationConvertRequest(BaseModel):
    start_child_world_draft: bool = True


class ObservationConvertResponse(BaseModel):
    observation_draft_id: str
    child_world_draft_id: str
    raw_media_deleted: bool


class ObservationRejectRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class ObservationRejectResponse(BaseModel):
    id: str
    status: str
    raw_media_deleted: bool


class ObservationHistoryDeleteResponse(BaseModel):
    id: str
    observation_draft_id: str | None = None
    raw_media_deleted: bool
    deleted_asset_ids: list[str] = Field(default_factory=list)


class MediaDeleteResponse(BaseModel):
    id: str
    status: str
    deleted_at: datetime | None


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
