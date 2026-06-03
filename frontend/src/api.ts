import type {
  CommunityRule,
  AgentRelationship,
  BranchPreview,
  ChildWorldDraft,
  GrowthReport,
  Persona,
  SimAgent,
  SimulationEvent,
  SimulationStepResponse,
  SimulationWorld,
  UserIntervention,
  WorldLocation,
  WorldSnapshot,
  WorldStateProjection
} from "./types";

const API = "/api";

export class ApiError extends Error {
  status: number;
  body: string;

  constructor(status: number, body: string) {
    super(body || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export async function api<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API}${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.text();
    const message = body.trim().startsWith("<") ? `HTTP ${response.status} ${response.statusText || "request failed"}` : body;
    throw new ApiError(response.status, message || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const authApi = {
  login: (username: string, password: string) =>
    api<{ access_token: string }>("/auth/login", "", {
      method: "POST",
      body: JSON.stringify({ username, password })
    }),
  me: (token: string) => api<{ username: string; role: "admin" | "user" }>("/auth/me", token),
  logout: (token: string) => api<{ status: string }>("/auth/logout", token, { method: "POST" })
};

export const personaApi = {
  list: (token: string) => api<Persona[]>("/personas", token),
  create: (
    token: string,
    payload: {
      name: string;
      description: string;
      persona_block: string;
      human_block: string;
      persona_type: string;
      consent_confirmed: boolean;
    }
  ) => api<Persona>("/personas", token, { method: "POST", body: JSON.stringify(payload) })
};

export const worldApi = {
  list: (token: string) => api<SimulationWorld[]>("/worlds", token),
  childDrafts: (token: string) => api<ChildWorldDraft[]>("/worlds/child-drafts", token),
  createChildDraft: (
    token: string,
    payload: {
      template_key?: string;
      child_name?: string;
      age_months?: number;
      caregiver_1_label?: string;
      caregiver_2_label?: string;
      kindergarten_class?: string;
      peer_count?: number;
      natural_language_prompt?: string;
      seed?: number;
    }
  ) => api<ChildWorldDraft>("/worlds/child-drafts", token, { method: "POST", body: JSON.stringify(payload) }),
  confirmChildDraft: (
    token: string,
    draftId: string,
    payload: { parsed_draft?: Record<string, unknown>; world_name?: string; seed?: number; start_running?: boolean }
  ) => api<SimulationWorld>(`/worlds/child-drafts/${draftId}/confirm`, token, { method: "POST", body: JSON.stringify(payload) }),
  create: (token: string, payload: { name: string; seed?: number; speed?: number; settings?: Record<string, unknown> }) =>
    api<SimulationWorld>("/worlds", token, { method: "POST", body: JSON.stringify(payload) }),
  update: (token: string, worldId: string, payload: Partial<Pick<SimulationWorld, "name" | "status" | "speed" | "settings">>) =>
    api<SimulationWorld>(`/worlds/${worldId}`, token, { method: "PATCH", body: JSON.stringify(payload) }),
  start: (token: string, worldId: string) => api<SimulationWorld>(`/worlds/${worldId}/start`, token, { method: "POST" }),
  pause: (token: string, worldId: string) => api<SimulationWorld>(`/worlds/${worldId}/pause`, token, { method: "POST" }),
  resume: (token: string, worldId: string) => api<SimulationWorld>(`/worlds/${worldId}/resume`, token, { method: "POST" }),
  step: (token: string, worldId: string) => api<SimulationStepResponse>(`/worlds/${worldId}/step`, token, { method: "POST" }),
  state: (token: string, worldId: string) => api<WorldStateProjection>(`/worlds/${worldId}/state`, token),
  events: (token: string, worldId: string, limit = 80) => api<SimulationEvent[]>(`/worlds/${worldId}/events?limit=${limit}`, token),
  createLocation: (
    token: string,
    worldId: string,
    payload: { name: string; kind?: string; x: number; y: number; description?: string; metadata?: Record<string, unknown> }
  ) => api<WorldLocation>(`/worlds/${worldId}/locations`, token, { method: "POST", body: JSON.stringify(payload) }),
  createAgent: (
    token: string,
    worldId: string,
    payload: {
      persona_id: string;
      name?: string;
      home_location_id?: string | null;
      current_location_id?: string | null;
      goals?: Record<string, unknown>;
      traits?: Record<string, unknown>;
      metadata?: Record<string, unknown>;
    }
  ) => api<SimAgent>(`/worlds/${worldId}/agents`, token, { method: "POST", body: JSON.stringify(payload) }),
  createRule: (
    token: string,
    worldId: string,
    payload: { title: string; content: string; priority?: number; status?: string; metadata?: Record<string, unknown> }
  ) => api<CommunityRule>(`/worlds/${worldId}/rules`, token, { method: "POST", body: JSON.stringify(payload) }),
  updateRule: (
    token: string,
    worldId: string,
    ruleId: string,
    payload: Partial<Pick<CommunityRule, "title" | "content" | "priority" | "status" | "metadata">>
  ) => api<CommunityRule>(`/worlds/${worldId}/rules/${ruleId}`, token, { method: "PATCH", body: JSON.stringify(payload) }),
  createIntervention: (
    token: string,
    worldId: string,
    payload: { actor?: string; intervention_type: string; payload: Record<string, unknown> }
  ) => api<UserIntervention>(`/worlds/${worldId}/interventions`, token, { method: "POST", body: JSON.stringify(payload) }),
  interventions: (token: string, worldId: string) => api<UserIntervention[]>(`/worlds/${worldId}/interventions`, token),
  relationships: (token: string, worldId: string) => api<AgentRelationship[]>(`/worlds/${worldId}/relationships`, token),
  growthReports: (token: string, worldId: string) => api<GrowthReport[]>(`/worlds/${worldId}/growth-reports`, token),
  snapshots: (token: string, worldId: string) => api<WorldSnapshot[]>(`/worlds/${worldId}/snapshots`, token),
  branchPreview: (token: string, worldId: string, payload: { snapshot_id?: string | null; label?: string }) =>
    api<BranchPreview>(`/worlds/${worldId}/branches/preview`, token, { method: "POST", body: JSON.stringify(payload) })
};
