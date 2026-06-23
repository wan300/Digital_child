export type Persona = {
  id: string;
  name: string;
  description: string;
  persona_type: string;
  consent_confirmed: boolean;
  persona_block: string;
  human_block: string;
  letta_agent_id?: string | null;
  status: string;
  created_at?: string;
  updated_at?: string;
};

export type Conversation = {
  id: string;
  persona_id: string;
  counterparty_user_id: string;
  title: string;
  channel: string;
};

export type Message = {
  id: string;
  role: string;
  content: string;
  context: Record<string, unknown>;
  created_at: string;
};

export type Evidence = {
  source: string;
  content: string;
  score?: number | null;
  source_ref?: {
    source_type: string;
    source_id?: string | null;
    provenance?: string;
    timestamp?: string | null;
  };
  metadata?: Record<string, unknown>;
};

export type MemoryRecord = {
  id: string;
  persona_id: string;
  counterparty_user_id?: string | null;
  scope?: string;
  content: string;
  subject: string;
  memory_type: string;
  confidence: number;
  sensitivity: string;
  decision: string;
  source_event_id?: string | null;
  external_id?: string | null;
};

export type Corpus = {
  id: string;
  persona_id: string;
  name: string;
  corpus_type: string;
  description?: string;
};

export type GeneratedMemoryDraft = {
  content: string;
  memory_type: string;
  confidence: number;
};

export type PersonaDraft = {
  name: string;
  description: string;
  persona_block: string;
  human_block: string;
  memories: GeneratedMemoryDraft[];
};

export type SimulationWorld = {
  id: string;
  name: string;
  status: string;
  clock_time: string;
  speed: number;
  seed: number;
  tick_no: number;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ChildWorldDraft = {
  id: string;
  status: string;
  template_key: string;
  input_params: Record<string, unknown>;
  natural_language_prompt: string;
  raw_response: string;
  parsed_draft: Record<string, unknown>;
  risk_flags: unknown[];
  created_world_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ChildObservationStructuredSetup = {
  template_key?: string;
  child_display_name?: string | null;
  child_name?: string | null;
  age_months?: number;
  caregiver_1_label?: string;
  caregiver_2_label?: string;
  kindergarten_class?: string;
  peer_count?: number;
  natural_language_prompt?: string;
  seed?: number | null;
};

export type ChildObservationMediaAsset = {
  id: string;
  owner_actor: string;
  original_filename: string;
  media_type: string;
  mime_type: string;
  sha256: string;
  size_bytes: number;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  preview_refs: unknown[];
  preview_retention: string;
  status: string;
  privacy_flags: unknown[];
  deletion_reason: string;
  deleted_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ChildObservationAssetStates = {
  analyzed: string[];
  pending: string[];
  skipped: string[];
  excluded: string[];
};

export type ChildObservationAnalysisJob = {
  id: string;
  status: string;
  phase: string;
  asset_states: ChildObservationAssetStates;
  asset_progress: Record<string, {
    asset_id?: string;
    filename?: string;
    media_type?: string;
    status?: string;
    frame_total?: number;
    frame_analyzed?: number;
    asr_status?: string;
    contribution_batches?: number[];
    error?: string;
  }>;
  frame_progress: {
    total: number;
    analyzed: number;
    failed: number;
    pending: number;
  };
  target_child: Record<string, unknown>;
  observation_draft_id: string | null;
  error_message: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ChildObservationReviewItem = {
  item_path: string;
  decision: "approved" | "edited" | "rejected" | "downgraded" | "unknown";
  final_value?: Record<string, unknown> | string | null;
  rationale?: string;
};

export type ChildObservationDraft = {
  id: string;
  status: string;
  analysis_job_id: string;
  child_world_draft_id: string | null;
  structured_setup: Record<string, unknown>;
  target_child: Record<string, unknown>;
  observable_summary: string;
  generated_child_description: string;
  accepted_child_description: string;
  visible_observations: unknown[];
  audio_observations: unknown[];
  non_identifying_appearance: unknown[];
  behavior_signals: unknown[];
  temperament_hypotheses: unknown[];
  interests: unknown[];
  development_hints: Record<string, unknown>;
  avatar_brief: Record<string, unknown>;
  initial_memory_candidates: unknown[];
  unknowns: unknown[];
  risk_flags: unknown[];
  authorization_confirmation: Record<string, unknown>;
  approved_payload: Record<string, unknown>;
  raw_media_deleted_at: string | null;
  asset_states?: ChildObservationAssetStates | null;
  preview_refs: unknown[];
  created_at: string;
  updated_at: string;
};

export type ChildObservationReviewResponse = {
  id: string;
  status: string;
  approved_payload: Record<string, unknown>;
  raw_media_deleted: boolean;
  raw_media_deletion_pending: boolean;
};

export type ChildObservationDescriptionAcceptResponse = {
  id: string;
  status: string;
  accepted_child_description: string;
  raw_media_deleted: boolean;
  risk_flags: unknown[];
};

export type ChildObservationConvertResponse = {
  observation_draft_id: string;
  child_world_draft_id: string;
  raw_media_deleted: boolean;
};

export type ChildObservationHistoryDeleteResponse = {
  id: string;
  observation_draft_id: string | null;
  raw_media_deleted: boolean;
  deleted_asset_ids: string[];
};

export type WorldLocation = {
  id: string;
  world_id: string;
  name: string;
  kind: string;
  x: number;
  y: number;
  description: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type CommunityRule = {
  id: string;
  world_id: string;
  title: string;
  content: string;
  priority: number;
  status: string;
  effective_from: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AgentState = {
  id: string;
  agent_id: string;
  needs: Record<string, unknown>;
  mood: string;
  plan: Record<string, unknown>;
  current_action: string;
  cooldowns: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

export type SimAgent = {
  id: string;
  world_id: string;
  persona_id: string;
  name: string;
  status: string;
  home_location_id: string | null;
  current_location_id: string | null;
  goals: Record<string, unknown>;
  traits: Record<string, unknown>;
  metadata: Record<string, unknown>;
  state: AgentState | null;
  created_at: string;
  updated_at: string;
};

export type AgentRelationship = {
  id: string;
  world_id: string;
  child_agent_id: string;
  npc_agent_id: string;
  relationship_type: string;
  metrics: Record<string, unknown>;
  evidence_buffer: unknown[];
  confidence: number;
  last_summary: string;
  created_at: string;
  updated_at: string;
};

export type AgentProjection = {
  id: string;
  persona_id: string;
  name: string;
  status: string;
  current_location_id: string | null;
  home_location_id: string | null;
  current_action: string;
  mood: string;
  goals: Record<string, unknown>;
  traits: Record<string, unknown>;
};

export type ChildProjection = {
  agent: SimAgent;
  location: WorldLocation | null;
  needs: Record<string, unknown>;
  development: Record<string, unknown>;
  key_memories: unknown[];
  half_day_summaries: unknown[];
};

export type SimulationEvent = {
  id: string;
  world_id: string;
  tick_no: number;
  event_type: string;
  source: string;
  status: string;
  reference_time: string;
  actors: unknown[];
  location_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type GrowthReport = {
  id: string;
  world_id: string;
  child_agent_id: string;
  period_start_tick: number;
  period_end_tick: number;
  report: Record<string, unknown>;
  source_event_id: string | null;
  created_at: string;
  updated_at: string;
};

export type WorldSnapshot = {
  id: string;
  world_id: string;
  tick_no: number;
  clock_time: string;
  state: Record<string, unknown>;
  event_cursor: string | null;
  created_at: string;
  updated_at: string;
};

export type BranchPreview = {
  world_id: string;
  available: boolean;
  message: string;
  requested_snapshot_id: string | null;
  data_shape: Record<string, unknown>;
};

export type UserIntervention = {
  id: string;
  world_id: string;
  actor: string;
  intervention_type: string;
  payload: Record<string, unknown>;
  status: string;
  result_event_id: string | null;
  created_at: string;
  updated_at: string;
};

export type RandomEventTemplate = {
  id: string;
  world_id: string;
  name: string;
  trigger: Record<string, unknown>;
  probability: number;
  cooldown: number;
  severity: string;
  effect_prompt: string;
  status: string;
  last_triggered_at: string | null;
  last_triggered_event_id: string | null;
  created_at: string;
  updated_at: string;
};

export type WorldStateProjection = {
  world: SimulationWorld;
  locations: WorldLocation[];
  agents: AgentProjection[];
  rules: CommunityRule[];
  recent_events: SimulationEvent[];
  child: ChildProjection | null;
  relationships: AgentRelationship[];
  growth_reports: GrowthReport[];
  snapshots: WorldSnapshot[];
  branch_preview: BranchPreview | null;
};

export type SimulationStepResponse = {
  world: SimulationWorld;
  events: SimulationEvent[];
  state: WorldStateProjection;
};
