from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RegularUser(Base, TimestampMixin):
    __tablename__ = "regular_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Persona(Base, TimestampMixin):
    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    persona_type: Mapped[str] = mapped_column(String(48), default="fictional_persona", nullable=False)
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    persona_block: Mapped[str] = mapped_column(Text, default="", nullable=False)
    human_block: Mapped[str] = mapped_column(Text, default="", nullable=False)
    letta_agent_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(48), default="draft", nullable=False)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="persona", cascade="all, delete-orphan")


class PersonaVersion(Base, TimestampMixin):
    __tablename__ = "persona_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True, nullable=False)
    counterparty_user_id: Mapped[str] = mapped_column(String(160), default="default-human", index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), default="新的对话", nullable=False)
    channel: Mapped[str] = mapped_column(String(80), default="web", nullable=False)

    persona: Mapped[Persona] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="web", nullable=False)
    reference_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MemoryRecord(Base, TimestampMixin):
    __tablename__ = "memory_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True, nullable=False)
    counterparty_user_id: Mapped[str | None] = mapped_column(String(160), index=True)
    scope: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(80), default="fact", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(40), default="normal", nullable=False)
    decision: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    source_event_id: Mapped[str | None] = mapped_column(String(36), index=True)
    external_id: Mapped[str | None] = mapped_column(String(160), index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)

    __table_args__ = (Index("ix_memory_persona_subject_decision", "persona_id", "subject", "decision"),)


class GraphEpisodeLink(Base, TimestampMixin):
    __tablename__ = "graph_episode_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True, nullable=False)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True, nullable=False)
    graph_group_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    graph_episode_uuid: Mapped[str | None] = mapped_column(String(160), index=True)
    reference_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Corpus(Base, TimestampMixin):
    __tablename__ = "corpora"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    corpus_type: Mapped[str] = mapped_column(String(80), default="background", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"), index=True, nullable=False)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="text/plain", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(180), index=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ImportJob(Base, TimestampMixin):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True, nullable=False)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class CoreMemoryProposal(Base, TimestampMixin):
    __tablename__ = "core_memory_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True, nullable=False)
    target_block: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(40), default="update", nullable=False)
    old_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    new_text: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(160), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(160))
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class EvalCase(Base, TimestampMixin):
    __tablename__ = "eval_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)


class EvalRun(Base, TimestampMixin):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    persona_id: Mapped[str | None] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(40), default="completed", nullable=False)
    results: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class SimulationWorld(Base, TimestampMixin):
    __tablename__ = "simulation_worlds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="paused", nullable=False, index=True)
    clock_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    speed: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    tick_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    locations: Mapped[list["WorldLocation"]] = relationship(back_populates="world", cascade="all, delete-orphan")
    agents: Mapped[list["SimAgent"]] = relationship(back_populates="world", cascade="all, delete-orphan")
    rules: Mapped[list["CommunityRule"]] = relationship(back_populates="world", cascade="all, delete-orphan")


class WorldLocation(Base, TimestampMixin):
    __tablename__ = "world_locations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    world_id: Mapped[str] = mapped_column(ForeignKey("simulation_worlds.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), default="place", nullable=False, index=True)
    x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    y: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)

    world: Mapped[SimulationWorld] = relationship(back_populates="locations")

    __table_args__ = (Index("ix_world_locations_world_name", "world_id", "name"),)


class CommunityRule(Base, TimestampMixin):
    __tablename__ = "community_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    world_id: Mapped[str] = mapped_column(ForeignKey("simulation_worlds.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False, index=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)

    world: Mapped[SimulationWorld] = relationship(back_populates="rules")

    __table_args__ = (Index("ix_community_rules_world_priority", "world_id", "priority"),)


class SimAgent(Base, TimestampMixin):
    __tablename__ = "sim_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    world_id: Mapped[str] = mapped_column(ForeignKey("simulation_worlds.id", ondelete="CASCADE"), index=True, nullable=False)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False, index=True)
    home_location_id: Mapped[str | None] = mapped_column(ForeignKey("world_locations.id", ondelete="SET NULL"), index=True)
    current_location_id: Mapped[str | None] = mapped_column(ForeignKey("world_locations.id", ondelete="SET NULL"), index=True)
    goals: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    traits: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)

    world: Mapped[SimulationWorld] = relationship(back_populates="agents")
    persona: Mapped[Persona] = relationship()
    home_location: Mapped[WorldLocation | None] = relationship(foreign_keys=[home_location_id])
    current_location: Mapped[WorldLocation | None] = relationship(foreign_keys=[current_location_id])
    state: Mapped["AgentState | None"] = relationship(back_populates="agent", cascade="all, delete-orphan", uselist=False)

    __table_args__ = (Index("ix_sim_agents_world_persona", "world_id", "persona_id"),)


class AgentState(Base, TimestampMixin):
    __tablename__ = "agent_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("sim_agents.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    needs: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    mood: Mapped[str] = mapped_column(String(80), default="neutral", nullable=False)
    plan: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    current_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cooldowns: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)

    agent: Mapped[SimAgent] = relationship(back_populates="state")


class SimulationAction(Base, TimestampMixin):
    __tablename__ = "simulation_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    world_id: Mapped[str] = mapped_column(ForeignKey("simulation_worlds.id", ondelete="CASCADE"), index=True, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("sim_agents.id", ondelete="SET NULL"), index=True)
    action_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), default="deterministic", nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class SimulationEvent(Base, TimestampMixin):
    __tablename__ = "simulation_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    world_id: Mapped[str] = mapped_column(ForeignKey("simulation_worlds.id", ondelete="CASCADE"), index=True, nullable=False)
    tick_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), default="simulation", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="completed", nullable=False, index=True)
    reference_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    actors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("world_locations.id", ondelete="SET NULL"), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (Index("ix_simulation_events_world_time", "world_id", "reference_time"),)


class RandomEventTemplate(Base, TimestampMixin):
    __tablename__ = "random_event_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    world_id: Mapped[str] = mapped_column(ForeignKey("simulation_worlds.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    trigger: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    probability: Mapped[float] = mapped_column(Float, default=0.1, nullable=False)
    cooldown: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    severity: Mapped[str] = mapped_column(String(40), default="info", nullable=False)
    effect_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False, index=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_triggered_event_id: Mapped[str | None] = mapped_column(String(36), index=True)


class UserIntervention(Base, TimestampMixin):
    __tablename__ = "user_interventions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    world_id: Mapped[str] = mapped_column(ForeignKey("simulation_worlds.id", ondelete="CASCADE"), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(160), default="system", nullable=False)
    intervention_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    result_event_id: Mapped[str | None] = mapped_column(String(36), index=True)


class WorldSnapshot(Base, TimestampMixin):
    __tablename__ = "world_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    world_id: Mapped[str] = mapped_column(ForeignKey("simulation_worlds.id", ondelete="CASCADE"), index=True, nullable=False)
    tick_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    clock_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    event_cursor: Mapped[str | None] = mapped_column(String(36), index=True)

    __table_args__ = (Index("ix_world_snapshots_world_tick", "world_id", "tick_no"),)


class ChildWorldDraft(Base, TimestampMixin):
    __tablename__ = "child_world_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    template_key: Mapped[str] = mapped_column(String(80), default="curious_outgoing", nullable=False, index=True)
    input_params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    natural_language_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raw_response: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parsed_draft: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_world_id: Mapped[str | None] = mapped_column(String(36), index=True)


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_actor: Mapped[str] = mapped_column(String(160), default="admin", nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(260), nullable=False)
    media_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_refs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="uploaded", nullable=False, index=True)
    privacy_flags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    deletion_reason: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)


class MediaAnalysisJob(Base, TimestampMixin):
    __tablename__ = "media_analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    asset_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    analyzed_asset_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    pending_asset_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    skipped_asset_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    excluded_asset_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    target_child: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    model_provider: Mapped[str] = mapped_column(String(80), default="local", nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    raw_response: Mapped[str] = mapped_column(Text, default="", nullable=False)
    normalized_result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChildMultimodalObservationDraft(Base, TimestampMixin):
    __tablename__ = "child_multimodal_observation_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    analysis_job_id: Mapped[str] = mapped_column(ForeignKey("media_analysis_jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    child_world_draft_id: Mapped[str | None] = mapped_column(ForeignKey("child_world_drafts.id", ondelete="SET NULL"), index=True, nullable=True)
    structured_setup: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    target_child: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    observable_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    generated_child_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    accepted_child_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    visible_observations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    audio_observations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    non_identifying_appearance: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    behavior_signals: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    temperament_hypotheses: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    interests: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    development_hints: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    avatar_brief: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    initial_memory_candidates: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    unknowns: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    authorization_confirmation: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    approved_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rejected_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raw_media_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    analysis_job: Mapped[MediaAnalysisJob] = relationship()
    child_world_draft: Mapped[ChildWorldDraft | None] = relationship()
    review_decisions: Mapped[list["ObservationReviewDecision"]] = relationship(
        back_populates="observation_draft",
        cascade="all, delete-orphan",
    )


class ObservationReviewDecision(Base, TimestampMixin):
    __tablename__ = "observation_review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    observation_draft_id: Mapped[str] = mapped_column(
        ForeignKey("child_multimodal_observation_drafts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    item_path: Mapped[str] = mapped_column(String(240), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    original_value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    final_value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)

    observation_draft: Mapped[ChildMultimodalObservationDraft] = relationship(back_populates="review_decisions")


class AgentRelationship(Base, TimestampMixin):
    __tablename__ = "agent_relationships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    world_id: Mapped[str] = mapped_column(ForeignKey("simulation_worlds.id", ondelete="CASCADE"), index=True, nullable=False)
    child_agent_id: Mapped[str] = mapped_column(ForeignKey("sim_agents.id", ondelete="CASCADE"), index=True, nullable=False)
    npc_agent_id: Mapped[str] = mapped_column(ForeignKey("sim_agents.id", ondelete="CASCADE"), index=True, nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_buffer: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.6, nullable=False)
    last_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (Index("ix_agent_relationships_world_pair", "world_id", "child_agent_id", "npc_agent_id"),)


class GrowthReport(Base, TimestampMixin):
    __tablename__ = "growth_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    world_id: Mapped[str] = mapped_column(ForeignKey("simulation_worlds.id", ondelete="CASCADE"), index=True, nullable=False)
    child_agent_id: Mapped[str] = mapped_column(ForeignKey("sim_agents.id", ondelete="CASCADE"), index=True, nullable=False)
    period_start_tick: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    period_end_tick: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    report: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(36), index=True)

    __table_args__ = (Index("ix_growth_reports_world_period", "world_id", "period_start_tick", "period_end_tick"),)
