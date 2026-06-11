import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Baby,
  BarChart3,
  BookOpen,
  Brain,
  Clock3,
  Eye,
  FileClock,
  Home,
  Map as MapIcon,
  Pause,
  Play,
  RefreshCw,
  School,
  Send,
  Sparkles,
  StepForward,
  Trees,
  Users
} from "lucide-react";
import { ApiError, worldApi } from "../api";
import type {
  AgentRelationship,
  BranchPreview,
  ChildWorldDraft,
  GrowthReport,
  SimulationEvent,
  SimulationWorld,
  UserIntervention,
  WorldLocation,
  WorldSnapshot,
  WorldStateProjection
} from "../types";
import { EmptyState } from "./EmptyState";

const DEFAULT_STEP_SECONDS = 5;
const STEP_RECOVERY_TTL_MS = 180_000;
const OBSERVER_RUNTIME_STORAGE_PREFIX = "child-growth-observer-runtime:";

type StoredStepState = {
  startedAt: number;
  tickNo: number | null;
};

type StoredObserverRuntime = {
  continuous?: boolean;
  stepSeconds?: number;
  stepping?: StoredStepState;
};

function clampStepSeconds(value: number) {
  if (!Number.isFinite(value)) return DEFAULT_STEP_SECONDS;
  return Math.min(120, Math.max(1, Math.round(value)));
}

function observerRuntimeKey(worldId: string) {
  return `${OBSERVER_RUNTIME_STORAGE_PREFIX}${worldId}`;
}

function isStoredStepState(value: unknown): value is StoredStepState {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  const tickNo = row.tickNo;
  return typeof row.startedAt === "number" && Number.isFinite(row.startedAt) && (tickNo === null || typeof tickNo === "number");
}

function readObserverRuntime(worldId: string): StoredObserverRuntime {
  if (!worldId) return {};
  try {
    const value = window.localStorage.getItem(observerRuntimeKey(worldId));
    if (!value) return {};
    const parsed = JSON.parse(value) as StoredObserverRuntime;
    return {
      continuous: parsed.continuous === true,
      stepSeconds: typeof parsed.stepSeconds === "number" ? clampStepSeconds(parsed.stepSeconds) : undefined,
      stepping: isStoredStepState(parsed.stepping) ? parsed.stepping : undefined
    };
  } catch {
    return {};
  }
}

function writeObserverRuntime(worldId: string, runtime: StoredObserverRuntime) {
  if (!worldId) return;
  try {
    window.localStorage.setItem(observerRuntimeKey(worldId), JSON.stringify(runtime));
  } catch {
    // Runtime persistence is a convenience guard; the UI still works without localStorage.
  }
}

function updateObserverRuntime(worldId: string, updater: (current: StoredObserverRuntime) => StoredObserverRuntime) {
  const next = updater(readObserverRuntime(worldId));
  writeObserverRuntime(worldId, next);
  return next;
}

function clearStoredStep(worldId: string) {
  updateObserverRuntime(worldId, (current) => {
    const { stepping: _stepping, ...rest } = current;
    return rest;
  });
}

function isFreshStepState(step: StoredStepState) {
  return Date.now() - step.startedAt < STEP_RECOVERY_TTL_MS;
}

const templateOptions = [
  ["curious_outgoing", "好奇外向型"],
  ["sensitive_slow_to_warm", "敏感慢热型"],
  ["quiet_focused", "安静专注型"],
  ["active_motor", "活泼运动型"]
] as const;

type DraftForm = {
  template_key: string;
  child_name: string;
  age_months: number;
  caregiver_1_label: string;
  caregiver_2_label: string;
  kindergarten_class: string;
  peer_count: number;
  natural_language_prompt: string;
  seed: number;
};

export function ObserverConsole({
  token
}: {
  token: string;
  personas: unknown[];
  refreshPersonas: () => Promise<void>;
}) {
  const [worlds, setWorlds] = useState<SimulationWorld[]>([]);
  const [drafts, setDrafts] = useState<ChildWorldDraft[]>([]);
  const [worldsLoaded, setWorldsLoaded] = useState(false);
  const [selectedWorldId, setSelectedWorldId] = useState("");
  const [state, setState] = useState<WorldStateProjection | null>(null);
  const [events, setEvents] = useState<SimulationEvent[]>([]);
  const [interventions, setInterventions] = useState<UserIntervention[]>([]);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState("");
  const [branchPreview, setBranchPreview] = useState<BranchPreview | null>(null);
  const [continuous, setContinuous] = useState(false);
  const [stepSeconds, setStepSeconds] = useState(DEFAULT_STEP_SECONDS);
  const [loading, setLoading] = useState(false);
  const [stepping, setStepping] = useState(false);
  const [recoveredStep, setRecoveredStep] = useState<StoredStepState | null>(null);
  const [runtimeHydratedWorldId, setRuntimeHydratedWorldId] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const steppingRef = useRef(false);
  const selectedWorldIdRef = useRef("");
  const currentTickRef = useRef<number | null>(null);

  const [draftForm, setDraftForm] = useState<DraftForm>({
    template_key: "curious_outgoing",
    child_name: "小雨",
    age_months: 48,
    caregiver_1_label: "照护者一",
    caregiver_2_label: "照护者二",
    kindergarten_class: "星星班",
    peer_count: 2,
    natural_language_prompt: "喜欢积木和自然观察，入园时需要一点过渡时间。",
    seed: 7
  });
  const [activeDraft, setActiveDraft] = useState<ChildWorldDraft | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);

  const childWorlds = useMemo(() => worlds.filter((world) => world.settings?.world_type === "child_growth_v1"), [worlds]);
  const selectedWorld = useMemo(
    () => state?.world || childWorlds.find((world) => world.id === selectedWorldId) || null,
    [childWorlds, selectedWorldId, state]
  );
  const selectedSnapshot = useMemo(
    () => state?.snapshots.find((snapshot) => snapshot.id === selectedSnapshotId) || null,
    [selectedSnapshotId, state?.snapshots]
  );
  const canShowDraftPanel = worldsLoaded && !selectedWorldId;

  useEffect(() => {
    selectedWorldIdRef.current = selectedWorldId;
  }, [selectedWorldId]);

  useEffect(() => {
    currentTickRef.current = state?.world.tick_no ?? selectedWorld?.tick_no ?? null;
  }, [selectedWorld?.tick_no, state?.world.tick_no]);

  useEffect(() => {
    setRuntimeHydratedWorldId("");
    if (!selectedWorldId) {
      setContinuous(false);
      setStepSeconds(DEFAULT_STEP_SECONDS);
      setRecoveredStep(null);
      steppingRef.current = false;
      setStepping(false);
      return;
    }

    const runtime = readObserverRuntime(selectedWorldId);
    const freshStep = runtime.stepping && isFreshStepState(runtime.stepping) ? runtime.stepping : null;
    if (runtime.stepping && !freshStep) clearStoredStep(selectedWorldId);

    setContinuous(runtime.continuous === true);
    setStepSeconds(runtime.stepSeconds ?? DEFAULT_STEP_SECONDS);
    setRecoveredStep(freshStep);
    steppingRef.current = Boolean(freshStep);
    setStepping(Boolean(freshStep));
    if (freshStep) {
      setNotice("检测到刷新前有半天演进可能仍在进行，正在恢复状态。");
    }
    setRuntimeHydratedWorldId(selectedWorldId);
  }, [selectedWorldId]);

  useEffect(() => {
    if (!selectedWorldId || runtimeHydratedWorldId !== selectedWorldId) return;
    updateObserverRuntime(selectedWorldId, (current) => ({
      ...current,
      continuous,
      stepSeconds: clampStepSeconds(stepSeconds)
    }));
  }, [continuous, runtimeHydratedWorldId, selectedWorldId, stepSeconds]);

  const refreshWorlds = useCallback(async () => {
    const [worldRows, draftRows] = await Promise.all([worldApi.list(token), worldApi.childDrafts(token)]);
    setWorlds(worldRows);
    setDrafts(draftRows);
    setSelectedWorldId((current) => {
      if (current && worldRows.some((world) => world.id === current)) return current;
      return worldRows.find((world) => world.settings?.world_type === "child_growth_v1" && world.status !== "archived")?.id || "";
    });
    setWorldsLoaded(true);
  }, [token]);

  const refreshState = useCallback(
    async (worldId = selectedWorldId, quiet = false) => {
      if (!worldId) {
        setState(null);
        setEvents([]);
        setInterventions([]);
        return null;
      }
      if (!quiet) setLoading(true);
      setError("");
      try {
        const [projected, fullEvents, interventionRows] = await Promise.all([
          worldApi.state(token, worldId),
          worldApi.events(token, worldId, 120),
          worldApi.interventions(token, worldId)
        ]);
        setState(projected);
        setEvents(fullEvents);
        setInterventions(interventionRows);
        setWorlds((items) => items.map((item) => (item.id === projected.world.id ? projected.world : item)));
        setSelectedSnapshotId((current) => current || projected.snapshots[0]?.id || "");
        return projected;
      } catch (err) {
        setError(err instanceof Error ? err.message : "刷新儿童世界失败");
        return null;
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [selectedWorldId, token]
  );

  const clearRecoveredStep = useCallback((worldId: string, message?: string) => {
    clearStoredStep(worldId);
    if (selectedWorldIdRef.current !== worldId) return;
    steppingRef.current = false;
    setStepping(false);
    setRecoveredStep(null);
    if (message) setNotice(message);
  }, []);

  useEffect(() => {
    if (!selectedWorldId || !recoveredStep) return;
    const currentTick = state?.world.tick_no;
    if (typeof currentTick === "number" && recoveredStep.tickNo !== null && currentTick > recoveredStep.tickNo) {
      clearRecoveredStep(selectedWorldId, "上一轮半天演进已完成，已恢复前端推进状态。");
      return;
    }
    if (!isFreshStepState(recoveredStep)) {
      clearRecoveredStep(selectedWorldId, "未检测到仍在进行的半天演进，已解除前端推进锁。");
    }
  }, [clearRecoveredStep, recoveredStep, selectedWorldId, state?.world.tick_no]);

  useEffect(() => {
    if (!selectedWorldId || !recoveredStep) return;
    const interval = window.setInterval(() => {
      if (!isFreshStepState(recoveredStep)) {
        clearRecoveredStep(selectedWorldId, "未检测到仍在进行的半天演进，已解除前端推进锁。");
        return;
      }
      void refreshState(selectedWorldId, true);
    }, 3000);
    return () => window.clearInterval(interval);
  }, [clearRecoveredStep, recoveredStep, refreshState, selectedWorldId]);

  useEffect(() => {
    refreshWorlds().catch((err) => setError(err instanceof Error ? err.message : "加载儿童世界失败"));
  }, [refreshWorlds]);

  useEffect(() => {
    refreshState(selectedWorldId).catch((err) => setError(err instanceof Error ? err.message : "加载世界状态失败"));
  }, [refreshState, selectedWorldId]);

  const createDraft = async () => {
    setDraftBusy(true);
    setError("");
    setNotice("");
    try {
      const draft = await worldApi.createChildDraft(token, draftForm);
      setActiveDraft(draft);
      await refreshWorlds();
      setNotice("初始化草稿已生成，请审核后确认创建。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成草稿失败");
    } finally {
      setDraftBusy(false);
    }
  };

  const confirmDraft = async (draft: ChildWorldDraft) => {
    setDraftBusy(true);
    setError("");
    setNotice("");
    try {
      const world = await worldApi.confirmChildDraft(token, draft.id, {
        parsed_draft: draft.parsed_draft,
        start_running: false,
        seed: draftForm.seed
      });
      setSelectedWorldId(world.id);
      setActiveDraft(null);
      await refreshWorlds();
      await refreshState(world.id);
      setNotice("儿童成长世界已创建，单步推进代表半天。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "确认草稿失败");
    } finally {
      setDraftBusy(false);
    }
  };

  const stepOnce = useCallback(
    async (options: { quiet?: boolean; ignoreConflict?: boolean } = {}) => {
      if (!selectedWorldId || steppingRef.current) return;
      const stepWorldId = selectedWorldId;
      const pendingStep: StoredStepState = { startedAt: Date.now(), tickNo: currentTickRef.current };
      let keepPendingStep = false;
      steppingRef.current = true;
      setStepping(true);
      setRecoveredStep(null);
      updateObserverRuntime(stepWorldId, (current) => ({ ...current, stepping: pendingStep }));
      setError("");
      if (!options.quiet) setNotice("");
      try {
        const response = await worldApi.step(token, stepWorldId);
        setState(response.state);
        setEvents((items) => mergeEvents(response.events, items));
        setWorlds((items) => items.map((item) => (item.id === response.world.id ? response.world : item)));
        await refreshState(response.world.id, true);
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          keepPendingStep = true;
          setContinuous(false);
          setNotice("上一轮半天演进仍在进行，已暂停连续演进。请稍后刷新状态后再推进。");
          setRecoveredStep(pendingStep);
          await refreshState(stepWorldId, true);
          if (!options.ignoreConflict) setError(formatStepError(err));
          return;
        }
        if (err instanceof ApiError && err.status === 504) {
          keepPendingStep = true;
          setContinuous(false);
          setNotice("半天演进请求超过网关等待时间，后端可能仍在处理。已暂停连续演进，稍后请刷新状态。");
          await delay(3000);
          const refreshed = await refreshState(stepWorldId, true);
          if (refreshed && pendingStep.tickNo !== null && refreshed.world.tick_no > pendingStep.tickNo) {
            keepPendingStep = false;
          } else {
            setRecoveredStep(pendingStep);
          }
          setError(formatStepError(err));
          return;
        }
        setContinuous(false);
        setError(err instanceof Error ? err.message : "推进半天失败");
      } finally {
        if (keepPendingStep) {
          if (selectedWorldIdRef.current === stepWorldId) {
            steppingRef.current = true;
            setStepping(true);
            setRecoveredStep(pendingStep);
          }
          return;
        }
        clearStoredStep(stepWorldId);
        if (selectedWorldIdRef.current === stepWorldId) {
          steppingRef.current = false;
          setStepping(false);
          setRecoveredStep(null);
        }
      }
    },
    [refreshState, selectedWorldId, token]
  );

  useEffect(() => {
    if (!continuous || !selectedWorldId) return;
    const interval = window.setInterval(() => {
      void stepOnce({ quiet: true, ignoreConflict: true });
    }, Math.max(1, stepSeconds) * 1000);
    return () => window.clearInterval(interval);
  }, [continuous, selectedWorldId, stepOnce, stepSeconds]);

  const setWorldRunning = async (running: boolean) => {
    if (!selectedWorldId) return;
    setError("");
    try {
      const world = running ? await worldApi.resume(token, selectedWorldId) : await worldApi.pause(token, selectedWorldId);
      setWorlds((items) => items.map((item) => (item.id === world.id ? world : item)));
      setState((current) => (current ? { ...current, world } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新运行状态失败");
    }
  };

  const previewBranch = async () => {
    if (!selectedWorldId) return;
    try {
      const preview = await worldApi.branchPreview(token, selectedWorldId, { snapshot_id: selectedSnapshotId || null, label: "观察台分支占位" });
      setBranchPreview(preview);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载分支占位失败");
    }
  };

  return (
    <section className="observer-console">
      <header className="observer-header">
        <div>
          <h1>儿童成长观察台</h1>
          <p>每次单步推进代表半天；连续演进只改变现实播放间隔。</p>
        </div>
        <div className="observer-selector">
          <select value={selectedWorldId} onChange={(event) => setSelectedWorldId(event.target.value)}>
            <option value="">选择儿童世界</option>
            {childWorlds.map((world) => (
              <option key={world.id} value={world.id}>
                {world.name}
              </option>
            ))}
          </select>
          <button onClick={() => refreshState()} disabled={!selectedWorldId || loading}>
            <RefreshCw size={16} />
            刷新
          </button>
        </div>
      </header>

      {notice && <div className="notice">{notice}</div>}
      {error && <div className="error">{error}</div>}

      {canShowDraftPanel && (
        <DraftPanel
          form={draftForm}
          setForm={setDraftForm}
          activeDraft={activeDraft}
          drafts={drafts}
          busy={draftBusy}
          onCreateDraft={createDraft}
          onConfirmDraft={confirmDraft}
          onSelectDraft={setActiveDraft}
        />
      )}

      {selectedWorld && (
        <SimulationControls
          world={selectedWorld}
          continuous={continuous}
          stepSeconds={stepSeconds}
          stepping={stepping}
          onStep={() => void stepOnce()}
          onToggleContinuous={() => setContinuous((value) => !value)}
          onStepSecondsChange={(value) => setStepSeconds(clampStepSeconds(value))}
          onSetRunning={setWorldRunning}
        />
      )}

      {!selectedWorld && childWorlds.length === 0 && <EmptyState text="还没有儿童成长世界。先生成草稿并审核确认。" />}
      {selectedWorld && !state && loading && <EmptyState text="正在加载儿童世界状态。" />}
      {selectedWorld && state && (
        <div className="observer-grid child-grid">
          <div className="child-main-stack">
            <SceneMap state={state} />
            <EventTimeline events={events.length ? events : state.recent_events} locations={state.locations} />
            <RelationshipPanel relationships={state.relationships} agents={state.agents} />
            <ReportPanel reports={state.growth_reports} />
          </div>
          <div className="child-side-stack">
            <ChildInspector state={state} />
            <InterventionPanel
              token={token}
              worldId={state.world.id}
              locations={state.locations}
              agents={state.agents}
              interventions={interventions}
              onChanged={async () => {
                await refreshState(state.world.id);
              }}
            />
            <ReplayPanel
              snapshots={state.snapshots}
              selectedSnapshot={selectedSnapshot}
              selectedSnapshotId={selectedSnapshotId}
              setSelectedSnapshotId={setSelectedSnapshotId}
              branchPreview={branchPreview || state.branch_preview}
              onPreviewBranch={previewBranch}
            />
          </div>
        </div>
      )}
    </section>
  );
}

function DraftPanel({
  form,
  setForm,
  activeDraft,
  drafts,
  busy,
  onCreateDraft,
  onConfirmDraft,
  onSelectDraft
}: {
  form: DraftForm;
  setForm: (form: DraftForm) => void;
  activeDraft: ChildWorldDraft | null;
  drafts: ChildWorldDraft[];
  busy: boolean;
  onCreateDraft: () => void;
  onConfirmDraft: (draft: ChildWorldDraft) => void;
  onSelectDraft: (draft: ChildWorldDraft | null) => void;
}) {
  const draft = activeDraft || drafts.find((item) => !item.created_world_id) || null;
  const child = asRecord(asRecord(draft?.parsed_draft).child);
  return (
    <section className="panel child-draft-panel">
      <div className="panel-heading">
        <div>
          <h2>初始化草稿</h2>
          <p>模板 + 少量参数 + 自然语言描述；确认前只生成草稿。</p>
        </div>
        <Sparkles size={20} />
      </div>
      <div className="draft-form-grid">
        <label>
          模板
          <select value={form.template_key} onChange={(event) => setForm({ ...form, template_key: event.target.value })}>
            {templateOptions.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          儿童称呼
          <input value={form.child_name} onChange={(event) => setForm({ ...form, child_name: event.target.value })} />
        </label>
        <label>
          年龄（月）
          <input type="number" min="36" max="72" value={form.age_months} onChange={(event) => setForm({ ...form, age_months: Number(event.target.value) || 48 })} />
        </label>
        <label>
          同伴数
          <input type="number" min="2" max="4" value={form.peer_count} onChange={(event) => setForm({ ...form, peer_count: Number(event.target.value) || 2 })} />
        </label>
        <label>
          照护者一称谓
          <input value={form.caregiver_1_label} onChange={(event) => setForm({ ...form, caregiver_1_label: event.target.value })} />
        </label>
        <label>
          照护者二称谓
          <input value={form.caregiver_2_label} onChange={(event) => setForm({ ...form, caregiver_2_label: event.target.value })} />
        </label>
        <label>
          幼儿园班级
          <input value={form.kindergarten_class} onChange={(event) => setForm({ ...form, kindergarten_class: event.target.value })} />
        </label>
        <label>
          随机种子
          <input type="number" value={form.seed} onChange={(event) => setForm({ ...form, seed: Number(event.target.value) || 1 })} />
        </label>
      </div>
      <textarea
        value={form.natural_language_prompt}
        onChange={(event) => setForm({ ...form, natural_language_prompt: event.target.value })}
        placeholder="只描述抽象特征，不输入真实儿童姓名、照片、病历、真实学校班级等可识别信息。"
      />
      <div className="inline">
        <button className="primary" onClick={onCreateDraft} disabled={busy}>
          <Sparkles size={16} />
          {busy ? "生成中" : "生成审核草稿"}
        </button>
        <select value={draft?.id || ""} onChange={(event) => onSelectDraft(drafts.find((item) => item.id === event.target.value) || null)}>
          <option value="">选择已有草稿</option>
          {drafts.map((item) => (
            <option key={item.id} value={item.id}>
              {item.template_key} · {item.status} · {formatDateTime(item.created_at)}
            </option>
          ))}
        </select>
      </div>
      {draft && (
        <article className="draft-review">
          <div>
            <strong>{safeString(child.name || "未命名儿童")}</strong>
            <small>{draft.status} · {draft.created_world_id ? "已创建世界" : "待确认"}</small>
          </div>
          <DraftReviewContent draft={draft} />
          {draft.risk_flags.length > 0 && (
            <span className="status-pill warning">
              <AlertTriangle size={14} />
              存在风险标记，需调整后确认
            </span>
          )}
          <button className="primary" onClick={() => onConfirmDraft(draft)} disabled={busy || !!draft.created_world_id || draft.risk_flags.length > 0}>
            <Baby size={16} />
            审核确认并创建
          </button>
        </article>
      )}
    </section>
  );
}

function DraftReviewContent({ draft }: { draft: ChildWorldDraft }) {
  const parsedDraft = asRecord(draft.parsed_draft);
  const world = asRecord(parsedDraft.world);
  const child = asRecord(parsedDraft.child);
  const traits = asRecord(child.traits);
  const needs = asRecord(child.needs);
  const development = asRecord(child.development);
  const initialMemories = asList(child.initial_memories);
  const locations = asList(parsedDraft.locations).map(asRecord);
  const npcs = asList(parsedDraft.npcs).map(asRecord);
  const relationships = draftRelationships(parsedDraft, npcs);

  return (
    <div className="draft-review-content">
      <section className="draft-section">
        <h3>润色后的草稿内容</h3>
        <div className="draft-summary-grid">
          <Detail label="世界名称" value={safeString(world.name || "未命名世界")} />
          <Detail label="儿童描述" value={safeString(child.description || "草稿已生成。")} />
        </div>
      </section>

      <section className="draft-section">
        <h3>核心设定</h3>
        <div className="draft-block-grid">
          <DraftTextBlock title="persona block" value={child.persona_block} />
          <DraftTextBlock title="human block" value={child.human_block} />
        </div>
      </section>

      <section className="draft-section">
        <h3>特征</h3>
        <DraftKeyValueGrid data={traits} />
      </section>

      <section className="draft-section">
        <h3>Needs</h3>
        {Object.keys(needs).length ? (
          <BarList rows={Object.entries(needs).map(([key, value]) => [needLabel(key), metricNumber(value)] as const)} />
        ) : (
          <EmptyState text="草稿中没有 needs 条目。" />
        )}
      </section>

      <section className="draft-section">
        <h3>发展基线</h3>
        {Object.keys(development).length ? (
          <div className="development-grid">
            {Object.entries(development).map(([key, value]) => {
              const row = asRecord(value);
              return (
                <article key={key}>
                  <strong>{developmentLabel(key)}</strong>
                  <Progress value={metricNumber(row.score)} />
                  <small>{safeString(row.trend || "stable")} · confidence {formatNumber(row.confidence)}</small>
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyState text="草稿中没有 development 条目。" />
        )}
      </section>

      <section className="draft-section">
        <h3>初始记忆</h3>
        {initialMemories.length ? (
          <ul className="draft-list">
            {initialMemories.map((memory, index) => (
              <li key={index}>{safeString(memory)}</li>
            ))}
          </ul>
        ) : (
          <EmptyState text="草稿中没有初始记忆。" />
        )}
      </section>

      <section className="draft-section">
        <h3>地点</h3>
        <DraftEntityList
          emptyText="草稿中没有地点。"
          items={locations}
          renderItem={(location, index) => (
            <article className="draft-entity" key={`${safeString(location.name)}-${index}`}>
              <strong>{safeString(location.name || "未命名地点")}</strong>
              <small>{safeString(location.kind || "place")}</small>
              <p>{safeString(location.description)}</p>
            </article>
          )}
        />
      </section>

      <section className="draft-section">
        <h3>NPC</h3>
        <DraftEntityList
          emptyText="草稿中没有 NPC。"
          items={npcs}
          renderItem={(npc, index) => (
            <article className="draft-entity" key={`${safeString(npc.name)}-${index}`}>
              <strong>{safeString(npc.display_label || npc.name || "未命名 NPC")}</strong>
              <small>
                {safeString(npc.role || "npc")} · {safeString(npc.relationship_type || "未设置关系类型")}
              </small>
              <p>{safeString(npc.description)}</p>
              {Object.keys(asRecord(npc.traits)).length > 0 && <DraftKeyValueGrid data={asRecord(npc.traits)} compact />}
            </article>
          )}
        />
      </section>

      <section className="draft-section">
        <h3>关系</h3>
        <DraftEntityList
          emptyText="草稿中没有关系条目，确认创建时会按角色生成默认关系。"
          items={relationships}
          renderItem={(relationship, index) => (
            <article className="draft-entity" key={`${safeString(relationship.relationship_type)}-${index}`}>
              <strong>{safeString(relationship.npc_name || relationship.name || relationship.relationship_type || relationship.type || `关系 ${index + 1}`)}</strong>
              <small>{safeString(relationship.relationship_type || relationship.type || "关系")}</small>
              <DraftKeyValueGrid data={relationship} compact />
            </article>
          )}
        />
      </section>

      <details className="draft-technical-details">
        <summary>技术详情：模型原始响应</summary>
        <pre>{draft.raw_response || "无原始响应"}</pre>
      </details>
    </div>
  );
}

function DraftTextBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <article className="draft-text-block">
      <strong>{title}</strong>
      <p>{safeString(value || "未填写")}</p>
    </article>
  );
}

function DraftKeyValueGrid({ data, compact = false }: { data: Record<string, unknown>; compact?: boolean }) {
  const entries = Object.entries(data);
  if (!entries.length) return <EmptyState text="没有可展示条目。" />;
  return (
    <dl className={compact ? "draft-key-values compact" : "draft-key-values"}>
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{formatDraftValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function DraftEntityList({
  items,
  emptyText,
  renderItem
}: {
  items: Record<string, unknown>[];
  emptyText: string;
  renderItem: (item: Record<string, unknown>, index: number) => ReactNode;
}) {
  if (!items.length) return <EmptyState text={emptyText} />;
  return <div className="draft-entity-grid">{items.map(renderItem)}</div>;
}

function draftRelationships(parsedDraft: Record<string, unknown>, npcs: Record<string, unknown>[]) {
  const explicitRelationships = asList(parsedDraft.relationships).map(asRecord);
  if (explicitRelationships.length) return explicitRelationships;
  return npcs.map((npc) => ({
    npc_name: safeString(npc.display_label || npc.name || "未命名 NPC"),
    relationship_type: safeString(npc.relationship_type || npc.role || "npc"),
    summary: "确认创建时会为该 NPC 生成初始关系记录。"
  }));
}

function SimulationControls({
  world,
  continuous,
  stepSeconds,
  stepping,
  onStep,
  onToggleContinuous,
  onStepSecondsChange,
  onSetRunning
}: {
  world: SimulationWorld;
  continuous: boolean;
  stepSeconds: number;
  stepping: boolean;
  onStep: () => void;
  onToggleContinuous: () => void;
  onStepSecondsChange: (value: number) => void;
  onSetRunning: (running: boolean) => Promise<void>;
}) {
  return (
    <section className="sim-controls panel">
      <Metric icon={<Clock3 size={18} />} label="世界时间" value={formatDateTime(world.clock_time)} />
      <Metric icon={<BarChart3 size={18} />} label="半天 step" value={String(world.tick_no)} />
      <Metric icon={<Eye size={18} />} label="状态" value={world.status} />
      <div className="control-actions">
        <button className="primary" onClick={onStep} disabled={stepping}>
          <StepForward size={16} />
          {stepping ? "推进中" : "推进半天"}
        </button>
        <button className={continuous ? "danger" : ""} onClick={onToggleContinuous} disabled={stepping && !continuous}>
          {continuous ? <Pause size={16} /> : <Play size={16} />}
          {continuous ? "停止连续" : "连续演进"}
        </button>
        <label className="compact-field">
          播放间隔秒
          <input type="number" min="1" max="120" value={stepSeconds} onChange={(event) => onStepSecondsChange(Number(event.target.value) || DEFAULT_STEP_SECONDS)} />
        </label>
        <button onClick={() => void onSetRunning(world.status !== "running")}>
          {world.status === "running" ? <Pause size={16} /> : <Play size={16} />}
          {world.status === "running" ? "标记暂停" : "标记运行"}
        </button>
      </div>
    </section>
  );
}

function SceneMap({ state }: { state: WorldStateProjection }) {
  const currentId = state.child?.agent.current_location_id;
  return (
    <section className="panel world-map-panel">
      <div className="panel-heading">
        <div>
          <h2>场景视图</h2>
          <p>家庭、幼儿园、社区/户外三类固定场景</p>
        </div>
        <MapIcon size={20} />
      </div>
      <div className="scene-strip">
        {state.locations.map((location) => {
          const Icon = location.kind === "home" ? Home : location.kind === "kindergarten" ? School : Trees;
          return (
            <article key={location.id} className={location.id === currentId ? "scene-card active" : "scene-card"}>
              <Icon size={22} />
              <strong>{location.name}</strong>
              <small>{location.description}</small>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ChildInspector({ state }: { state: WorldStateProjection }) {
  const child = state.child;
  if (!child) {
    return (
      <section className="panel agent-inspector">
        <h2>儿童详情</h2>
        <EmptyState text="该世界还没有儿童主角。" />
      </section>
    );
  }
  const previousNeeds = previousSnapshotNeeds(state);
  return (
    <section className="panel agent-inspector child-inspector">
      <div className="panel-heading">
        <div>
          <h2>{child.agent.name}</h2>
          <p>{child.location?.name || "未知场景"} · {child.agent.state?.mood || "calm"}</p>
        </div>
        <Baby size={20} />
      </div>
      <Detail label="当前行动" value={child.agent.state?.current_action || "等待下一段半天经历"} />
      <h3>Needs</h3>
      <BarList
        rows={Object.entries(child.needs).map(([key, value]) => {
          const currentValue = metricNumber(value);
          const hasPreviousValue = previousNeeds ? Object.prototype.hasOwnProperty.call(previousNeeds, key) : false;
          const previousValue = hasPreviousValue && previousNeeds ? metricNumber(previousNeeds[key]) : null;
          return [needLabel(key), currentValue, previousValue === null ? null : currentValue - previousValue] as const;
        })}
      />
      <h3>发展域</h3>
      <div className="development-grid">
        {Object.entries(child.development).map(([key, value]) => {
          const row = asRecord(value);
          return (
            <article key={key}>
              <strong>{developmentLabel(key)}</strong>
              <Progress value={metricNumber(row.score)} />
              <small>{safeString(row.trend || "stable")} · confidence {formatNumber(row.confidence)}</small>
            </article>
          );
        })}
      </div>
      <div className="mini-list">
        <h3>半天记录</h3>
        {child.half_day_summaries.slice(-4).reverse().map((item, index) => {
          const row = asRecord(item);
          const lifeSlice = readLifeSlice(row.life_slice);
          return (
            <article key={`${row.tick_no}-${index}`}>
              <strong>step {safeString(row.tick_no)}</strong>
              <p>{safeString(row.summary)}</p>
              <small>{safeString(row.child_interpretation)}</small>
              {lifeSlice && <LifeSliceView lifeSlice={lifeSlice} />}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function previousSnapshotNeeds(state: WorldStateProjection): Record<string, unknown> | null {
  const previousSnapshot = state.snapshots.find((snapshot) => snapshot.tick_no < state.world.tick_no);
  if (!previousSnapshot) return null;
  const child = asRecord(previousSnapshot.state.child);
  const needs = asRecord(child.needs);
  return Object.keys(needs).length ? needs : null;
}

function RelationshipPanel({ relationships, agents }: { relationships: AgentRelationship[]; agents: { id: string; name: string }[] }) {
  return (
    <section className="panel relationship-panel">
      <div className="panel-heading">
        <div>
          <h2>关系边</h2>
          <p>{relationships.length} 条儿童-NPC 关系</p>
        </div>
        <Users size={20} />
      </div>
      {!relationships.length && <EmptyState text="还没有关系数据。" />}
      <div className="relationship-list">
        {relationships.map((relationship) => (
          <article key={relationship.id}>
            <strong>{agents.find((agent) => agent.id === relationship.npc_agent_id)?.name || relationship.npc_agent_id.slice(0, 8)}</strong>
            <small>{relationshipLabel(relationship.relationship_type)} · confidence {relationship.confidence.toFixed(2)}</small>
            <BarList
              rows={Object.entries(relationship.metrics)
                .slice(0, 6)
                .map(([key, value]) => [relationshipMetricLabel(key), metricNumber(value)] as const)}
            />
            <p>{relationship.last_summary}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function InterventionPanel({
  token,
  worldId,
  locations,
  agents,
  interventions,
  onChanged
}: {
  token: string;
  worldId: string;
  locations: WorldLocation[];
  agents: WorldStateProjection["agents"];
  interventions: UserIntervention[];
  onChanged: () => Promise<void>;
}) {
  const [type, setType] = useState("environment_event");
  const [text, setText] = useState("");
  const [locationId, setLocationId] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [agentId, setAgentId] = useState("");
  const [activityGoal, setActivityGoal] = useState("");
  const [guidanceStyle, setGuidanceStyle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const targetAgents = agents.filter((agent) => {
    const role = safeString(agent.traits?.role);
    if (role === "child") return false;
    return !targetRole || role === targetRole;
  });

  const submit = async () => {
    if (!text.trim() || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await worldApi.createIntervention(token, worldId, {
        intervention_type: type,
        payload: {
          text: text.trim(),
          location_id: locationId || undefined,
          target_role: targetRole || undefined,
          agent_id: agentId || undefined,
          activity_goal: activityGoal.trim() || undefined,
          guidance_style: guidanceStyle.trim() || undefined
        }
      });
      setText("");
      setActivityGoal("");
      setGuidanceStyle("");
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交干预失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel intervention-panel">
      <div className="panel-heading">
        <div>
          <h2>间接干预</h2>
          <p>不能直接编辑儿童状态，只能注入环境、成人或 NPC 事件。</p>
        </div>
        <Send size={20} />
      </div>
      {error && <p className="error">{error}</p>}
      <textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="例如：老师今天在入园时蹲下来提醒，妈妈会在午后准时来接。" />
      <div className="inline">
        <select value={type} onChange={(event) => setType(event.target.value)}>
          <option value="environment_event">环境事件</option>
          <option value="adult_behavior">成人行为</option>
          <option value="npc_behavior">NPC 行为</option>
          <option value="rule_change">规则变化</option>
          <option value="gm_event">GM 事件</option>
        </select>
        <select value={locationId} onChange={(event) => setLocationId(event.target.value)}>
          <option value="">全局</option>
          {locations.map((location) => (
            <option key={location.id} value={location.id}>
              {location.name}
            </option>
          ))}
        </select>
        <select
          value={targetRole}
          onChange={(event) => {
            setTargetRole(event.target.value);
            setAgentId("");
          }}
        >
          <option value="">不指定角色</option>
          <option value="caregiver">家庭成人</option>
          <option value="teacher">老师</option>
          <option value="peer">同伴</option>
        </select>
        <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
          <option value="">不指定人物</option>
          {targetAgents.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </select>
      </div>
      <div className="inline">
        <input
          value={activityGoal}
          onChange={(event) => setActivityGoal(event.target.value)}
          placeholder="活动目标，例如：积木合作活动"
        />
        <input
          value={guidanceStyle}
          onChange={(event) => setGuidanceStyle(event.target.value)}
          placeholder="引导方式，例如：蹲下来分步骤提示"
        />
        <button className="primary" onClick={submit} disabled={!text.trim() || submitting}>
          <Send size={16} />
          注入
        </button>
      </div>
      <div className="mini-list">
        <h3>近期干预</h3>
        {!interventions.length && <EmptyState text="还没有干预记录。" />}
        {interventions.slice(0, 4).map((intervention) => {
          const payload = asRecord(intervention.payload);
          const detail = [
            interventionRoleLabel(safeString(payload.target_role)),
            safeString(payload.activity_goal),
            safeString(payload.guidance_style)
          ].filter(Boolean);
          return (
            <article key={intervention.id}>
              <strong>{safeString(payload.text || intervention.intervention_type)}</strong>
              {detail.length > 0 && <p>{detail.join(" · ")}</p>}
              <small>
                {intervention.status} · {formatDateTime(intervention.created_at)}
                {intervention.result_event_id ? ` · 已关联事件 ${intervention.result_event_id.slice(0, 8)}` : ""}
              </small>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ReportPanel({ reports }: { reports: GrowthReport[] }) {
  const latest = reports[0];
  return (
    <section className="panel report-panel">
      <div className="panel-heading">
        <div>
          <h2>7 天报告</h2>
          <p>{latest ? `step ${latest.period_start_tick}-${latest.period_end_tick}` : "每 14 step 自动生成"}</p>
        </div>
        <BookOpen size={20} />
      </div>
      {!latest && <EmptyState text="运行满 7 天后生成第一份报告。" />}
      {latest && (
        <div className="report-body">
          <ReportSection title="主要经历" value={latest.report.major_experiences} />
          <ReportSection title="情绪模式" value={latest.report.emotional_patterns} />
          <ReportSection title="下周关注" value={latest.report.next_week_focus} />
          <small>{safeString(latest.report.disclaimer)}</small>
        </div>
      )}
    </section>
  );
}

function ReplayPanel({
  snapshots,
  selectedSnapshot,
  selectedSnapshotId,
  setSelectedSnapshotId,
  branchPreview,
  onPreviewBranch
}: {
  snapshots: WorldSnapshot[];
  selectedSnapshot: WorldSnapshot | null;
  selectedSnapshotId: string;
  setSelectedSnapshotId: (value: string) => void;
  branchPreview: BranchPreview | null;
  onPreviewBranch: () => void;
}) {
  return (
    <section className="panel replay-panel">
      <div className="panel-heading">
        <div>
          <h2>回放与分支占位</h2>
          <p>{snapshots.length} 个历史快照</p>
        </div>
        <FileClock size={20} />
      </div>
      <div className="inline">
        <select value={selectedSnapshotId} onChange={(event) => setSelectedSnapshotId(event.target.value)}>
          <option value="">选择快照</option>
          {snapshots.map((snapshot) => (
            <option key={snapshot.id} value={snapshot.id}>
              step {snapshot.tick_no} · {formatDateTime(snapshot.clock_time)}
            </option>
          ))}
        </select>
        <button onClick={onPreviewBranch} disabled={!selectedSnapshotId}>
          <FileClock size={16} />
          分支预览
        </button>
      </div>
      {selectedSnapshot ? (
        <article className="snapshot-card">
          <strong>step {selectedSnapshot.tick_no}</strong>
          <p>{safeString(asRecord(asRecord(selectedSnapshot.state.child).metadata).half_day_summaries ? "包含儿童状态快照、关系和事件游标。" : "历史快照已保存。")}</p>
          <small>event cursor: {selectedSnapshot.event_cursor || "none"}</small>
        </article>
      ) : (
        <EmptyState text="还没有可回放快照。" />
      )}
      {branchPreview && (
        <article className="snapshot-card">
          <strong>{branchPreview.available ? "可运行分支" : "分支接口占位"}</strong>
          <p>{branchPreview.message}</p>
        </article>
      )}
    </section>
  );
}

function EventTimeline({ events, locations }: { events: SimulationEvent[]; locations: WorldLocation[] }) {
  return (
    <section className="panel event-timeline">
      <div className="panel-heading">
        <div>
          <h2>半天时间线</h2>
          <p>{events.length} 条近期事件</p>
        </div>
        <Clock3 size={20} />
      </div>
      {!events.length && <EmptyState text="还没有半天事件。" />}
      {events.map((event) => {
        const location = locations.find((item) => item.id === event.location_id);
        const lifeSlice = readLifeSlice(event.payload.life_slice);
        return (
          <article key={event.id} className={event.status === "needs_review" ? "event-item needs-review" : "event-item"}>
            <div>
              <strong>{safeString(event.payload.half_day_summary || event.payload.summary || event.event_type)}</strong>
              <p>{safeString(event.payload.child_interpretation || event.payload.action_text || "")}</p>
              {lifeSlice && <LifeSliceView lifeSlice={lifeSlice} />}
              <details>
                <summary>GM 解释与证据</summary>
                <p className="muted">
                  来源：{safeString(event.payload.gm_source || "unknown")}
                  {event.payload.concordia_wrapper_error
                    ? ` · wrapper: ${safeString(event.payload.concordia_wrapper_error)}`
                    : ""}
                </p>
                <p>{safeString(event.payload.gm_interpretation || "无 GM 解释。")}</p>
                <pre>{JSON.stringify(event.payload.state_update_evidence || [], null, 2)}</pre>
              </details>
            </div>
            <small>
              step {event.tick_no} · {event.event_type} · {formatDateTime(event.reference_time)}
              {location ? ` · ${location.name}` : ""}
            </small>
          </article>
        );
      })}
    </section>
  );
}

type LifeSlice = {
  sceneDescription: string;
  dialogue: { speaker: string; text: string }[];
};

function LifeSliceView({ lifeSlice }: { lifeSlice: LifeSlice }) {
  return (
    <div className="life-slice">
      {lifeSlice.sceneDescription && <p className="life-slice-scene">{lifeSlice.sceneDescription}</p>}
      <div className="life-slice-dialogue">
        {lifeSlice.dialogue.map((turn, index) => (
          <p key={`${turn.speaker}-${index}`}>
            <strong>{turn.speaker}</strong>
            <span>{turn.text}</span>
          </p>
        ))}
      </div>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="metric">
      {icon}
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

type BarListRow = readonly [string, number] | readonly [string, number, number | null];

function BarList({ rows }: { rows: readonly BarListRow[] }) {
  return (
    <div className="bar-list">
      {rows.map(([label, value, delta]) => (
        <div key={label} className="bar-row">
          <span>{label}</span>
          <Progress value={value} />
          <strong className="bar-value">
            {value}
            {delta !== null && delta !== undefined && delta !== 0 && (
              <span className={delta > 0 ? "metric-delta positive" : "metric-delta negative"}>
                {delta > 0 ? `+${delta}` : delta}
              </span>
            )}
          </strong>
        </div>
      ))}
    </div>
  );
}

function Progress({ value }: { value: number }) {
  return (
    <div className="progress-track">
      <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

function ReportSection({ title, value }: { title: string; value: unknown }) {
  const values = Array.isArray(value) ? value.map(safeString) : [safeString(value)];
  return (
    <div>
      <h3>{title}</h3>
      {values.map((item, index) => (
        <p key={`${title}-${index}`}>{item}</p>
      ))}
    </div>
  );
}

function mergeEvents(newEvents: SimulationEvent[], oldEvents: SimulationEvent[]) {
  const map = new Map<string, SimulationEvent>();
  [...newEvents, ...oldEvents].forEach((event) => map.set(event.id, event));
  return Array.from(map.values()).sort((a, b) => b.tick_no - a.tick_no || b.created_at.localeCompare(a.created_at)).slice(0, 120);
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function formatStepError(err: ApiError) {
  if (err.status === 409) return "上一轮半天演进仍在进行，请等它完成后再推进。";
  if (err.status === 504) return "网关等待后端演进超时。后端可能仍在处理，请稍后刷新状态。";
  const body = err.body.trim();
  if (body.startsWith("<")) return `请求失败：HTTP ${err.status}`;
  return body || `请求失败：HTTP ${err.status}`;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function formatDraftValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未填写";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function readLifeSlice(value: unknown): LifeSlice | null {
  const row = asRecord(value);
  const sceneDescription = safeString(row.scene_description || row.sceneDescription || row.scene);
  const rawDialogue = Array.isArray(row.dialogue) ? row.dialogue : [];
  const dialogue = rawDialogue
    .map((item) => {
      if (typeof item === "string" && item.includes("：")) {
        const [speaker, ...rest] = item.split("：");
        return { speaker: speaker.trim(), text: rest.join("：").trim() };
      }
      const turn = asRecord(item);
      return {
        speaker: safeString(turn.speaker || turn.role),
        text: safeString(turn.text || turn.line || turn.content)
      };
    })
    .filter((turn) => turn.speaker && turn.text)
    .slice(0, 20);
  if (!sceneDescription && !dialogue.length) return null;
  return { sceneDescription, dialogue };
}

function metricNumber(value: unknown): number {
  return typeof value === "number" ? Math.round(value) : Number(value) || 0;
}

function safeString(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function formatNumber(value: unknown): string {
  return typeof value === "number" ? value.toFixed(2) : safeString(value || "0.00");
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function needLabel(key: string) {
  return (
    {
      energy: "精力",
      satiety: "饱腹",
      sleep_quality: "睡眠",
      health: "健康",
      hygiene: "卫生",
      safety: "安全感",
      stress: "压力"
    }[key] || key
  );
}

function developmentLabel(key: string) {
  return (
    {
      language_communication: "语言沟通",
      cognitive_attention: "认知注意",
      motor_ability: "运动能力",
      emotional_regulation: "情绪调节",
      social_cooperation: "社交合作",
      self_care_habits: "自理习惯"
    }[key] || key
  );
}

function relationshipLabel(key: string) {
  return ({ caregiver: "家庭成人", teacher: "老师", peer: "同伴" }[key] || key);
}

function interventionRoleLabel(key: string) {
  if (!key) return "";
  return ({ caregiver: "家庭成人", teacher: "老师", peer: "同伴" }[key] || key);
}

function relationshipMetricLabel(key: string) {
  return (
    {
      familiarity: "熟悉度",
      warmth: "温暖",
      trust_security: "信任安全",
      tension: "紧张",
      care_consistency: "照护一致",
      separation_comfort: "分离舒适",
      guidance_acceptance: "引导接受",
      classroom_comfort: "班级舒适",
      play_preference: "游戏偏好",
      cooperation_fit: "合作契合"
    }[key] || key
  );
}
