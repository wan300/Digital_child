import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  Brain,
  Check,
  Clock3,
  Database,
  FileText,
  MessageSquare,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2
} from "lucide-react";
import { api, worldApi } from "../api";
import type {
  Conversation,
  Corpus,
  Evidence,
  GeneratedMemoryDraft,
  MemoryRecord,
  Message,
  Persona,
  PersonaDraft,
  SimAgent,
  SimulationWorld
} from "../types";
import { EmptyState } from "./EmptyState";

const managementTabs = [
  ["chat", "对话", MessageSquare],
  ["personas", "人格", Bot],
  ["memory", "记忆", Brain],
  ["timeline", "时间线", Clock3],
  ["documents", "文档", FileText],
  ["evals", "评测", Play],
  ["settings", "设置", Settings]
] as const;

type ManagementView = (typeof managementTabs)[number][0];

type PersonaWorldAgent = {
  agent: SimAgent;
  persona?: Persona;
};

type PersonaWorldGroup = {
  world: SimulationWorld;
  agents: PersonaWorldAgent[];
  failed?: boolean;
};

const roleLabels: Record<string, string> = {
  child: "儿童",
  caregiver: "照护者",
  teacher: "老师",
  peer: "同伴",
  npc: "角色"
};

function isChildGrowthWorld(world: SimulationWorld) {
  return world.settings?.world_type === "child_growth_v1";
}

function agentRole(agent: SimAgent) {
  const role = agent.traits?.role;
  return typeof role === "string" && role ? role : "npc";
}

function agentRoleLabel(agent: SimAgent) {
  const role = agentRole(agent);
  return roleLabels[role] || role;
}

export function ManagementConsole({
  token,
  personas,
  selectedPersonaId,
  setSelectedPersonaId,
  refreshPersonas,
  notice
}: {
  token: string;
  personas: Persona[];
  selectedPersonaId: string;
  setSelectedPersonaId: (id: string) => void;
  refreshPersonas: () => Promise<void>;
  notice: string;
}) {
  const [view, setView] = useState<ManagementView>("personas");
  const [worldGroups, setWorldGroups] = useState<PersonaWorldGroup[]>([]);
  const [worldGroupsLoading, setWorldGroupsLoading] = useState(false);
  const [worldGroupError, setWorldGroupError] = useState("");
  const selectedPersona = useMemo(
    () => personas.find((persona) => persona.id === selectedPersonaId),
    [personas, selectedPersonaId]
  );
  const assignedPersonaIds = useMemo(() => {
    const ids = new Set<string>();
    for (const group of worldGroups) {
      for (const row of group.agents) ids.add(row.agent.persona_id);
    }
    return ids;
  }, [worldGroups]);
  const unassignedPersonas = useMemo(
    () => personas.filter((persona) => !assignedPersonaIds.has(persona.id)),
    [assignedPersonaIds, personas]
  );
  const showUnassignedPersonas = !worldGroupsLoading || worldGroups.length > 0;

  const refreshWorldGroups = useCallback(async () => {
    setWorldGroupsLoading(true);
    setWorldGroupError("");
    try {
      const worlds = (await worldApi.list(token)).filter(isChildGrowthWorld);
      const personaById = new Map(personas.map((persona) => [persona.id, persona]));
      const results = await Promise.allSettled(worlds.map((world) => worldApi.agents(token, world.id)));
      const groups = worlds.map((world, index) => {
        const result = results[index];
        if (result.status !== "fulfilled") {
          return { world, agents: [], failed: true };
        }
        return {
          world,
          agents: result.value.map((agent) => ({
            agent,
            persona: personaById.get(agent.persona_id)
          }))
        };
      });
      setWorldGroups(groups);
      if (results.some((result) => result.status === "rejected")) {
        setWorldGroupError("部分儿童世界角色加载失败。");
      }
    } catch (err) {
      setWorldGroups([]);
      setWorldGroupError(err instanceof Error ? err.message : "加载儿童世界角色失败");
    } finally {
      setWorldGroupsLoading(false);
    }
  }, [personas, token]);

  useEffect(() => {
    refreshWorldGroups().catch(console.error);
  }, [refreshWorldGroups]);

  return (
    <section className="management-console">
      <header className="topbar">
        <div>
          <h1>管理区</h1>
          <p>当前人格：{selectedPersona?.name || "未选择"}</p>
        </div>
        <select value={selectedPersonaId} onChange={(event) => setSelectedPersonaId(event.target.value)}>
          <option value="">选择人格</option>
          {worldGroups.map((group) => (
            <optgroup key={group.world.id} label={group.world.name}>
              {group.agents.map(({ agent, persona }) => (
                <option key={`${group.world.id}-${agent.id}`} value={agent.persona_id}>
                  {(persona?.name || agent.name) + `（${agentRoleLabel(agent)}）`}
                </option>
              ))}
            </optgroup>
          ))}
          {showUnassignedPersonas && unassignedPersonas.length > 0 && (
            <optgroup label="未绑定儿童世界">
              {unassignedPersonas.map((persona) => (
                <option key={persona.id} value={persona.id}>
                  {persona.name}
                </option>
              ))}
            </optgroup>
          )}
          {worldGroupsLoading && worldGroups.length === 0 && <option disabled>正在加载儿童世界角色</option>}
        </select>
      </header>
      {notice && <div className="notice">{notice}</div>}
      <div className="tabbar">
        {managementTabs.map(([id, label, Icon]) => (
          <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>
            <Icon size={16} />
            {label}
          </button>
        ))}
      </div>
      {view === "chat" && <ChatPage token={token} personaId={selectedPersonaId} />}
      {view === "personas" && (
        <PersonaPage
          token={token}
          personas={personas}
          refresh={refreshPersonas}
          worldGroups={worldGroups}
          worldGroupsLoading={worldGroupsLoading}
          worldGroupError={worldGroupError}
          refreshWorldGroups={refreshWorldGroups}
        />
      )}
      {view === "memory" && <MemoryPage token={token} personaId={selectedPersonaId} />}
      {view === "timeline" && <TimelinePage token={token} personaId={selectedPersonaId} />}
      {view === "documents" && <DocumentsPage token={token} personaId={selectedPersonaId} />}
      {view === "evals" && <EvalPage token={token} personaId={selectedPersonaId} />}
      {view === "settings" && <SettingsPage token={token} />}
    </section>
  );
}

function ChatPage({ token, personaId }: { token: string; personaId: string }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const refresh = async () => {
    if (!personaId) return;
    const data = await api<Conversation[]>(`/conversations?persona_id=${personaId}`, token);
    setConversations(data);
    if (!conversationId && data[0]) setConversationId(data[0].id);
  };

  const loadConversation = async (id: string) => {
    if (!id) return;
    const data = await api<Conversation & { messages: Message[] }>(`/conversations/${id}`, token);
    setMessages(data.messages || []);
  };

  useEffect(() => {
    refresh().catch(console.error);
  }, [personaId]);

  useEffect(() => {
    loadConversation(conversationId).catch(console.error);
  }, [conversationId]);

  const createConversation = async () => {
    if (!personaId) return;
    const data = await api<Conversation>("/conversations", token, {
      method: "POST",
      body: JSON.stringify({ persona_id: personaId, title: "新的对话", counterparty_user_id: "default-human" })
    });
    setConversations([data, ...conversations]);
    setConversationId(data.id);
    setMessages([]);
  };

  const send = async () => {
    const content = input.trim();
    if (!conversationId || !content || sending) return;
    setSending(true);
    setError("");
    try {
      const data = await api<{
        user_message: Message;
        assistant_message: Message;
        context_bundle: { long_term_memories: Evidence[]; temporal_facts: Evidence[]; document_evidence: Evidence[] };
      }>(`/conversations/${conversationId}/messages`, token, {
        method: "POST",
        body: JSON.stringify({ content })
      });
      setMessages((items) => [...items, data.user_message, data.assistant_message]);
      setEvidence([
        ...(data.context_bundle.long_term_memories || []),
        ...(data.context_bundle.temporal_facts || []),
        ...(data.context_bundle.document_evidence || [])
      ]);
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="split">
      <div className="panel main-panel">
        <div className="toolbar">
          <button className="primary" onClick={createConversation} disabled={!personaId}>
            <Plus size={16} />
            新建对话
          </button>
          <select value={conversationId} onChange={(event) => setConversationId(event.target.value)}>
            <option value="">选择会话</option>
            {conversations.map((conversation) => (
              <option key={conversation.id} value={conversation.id}>
                {conversation.title}
              </option>
            ))}
          </select>
        </div>
        <div className="messages">
          {!messages.length && <EmptyState text="还没有消息。" />}
          {messages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <span>{message.role === "user" ? "用户" : "人格"}</span>
              <p>{message.content}</p>
            </article>
          ))}
        </div>
        <div className="composer">
          <textarea value={input} onChange={(event) => setInput(event.target.value)} placeholder="输入消息" />
          <button className="primary" onClick={send} disabled={!conversationId || !input.trim() || sending}>
            {sending ? "发送中" : "发送"}
          </button>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
      <EvidencePanel evidence={evidence} />
    </section>
  );
}

function EvidencePanel({ evidence }: { evidence: Evidence[] }) {
  return (
    <aside className="panel evidence">
      <h2>上下文证据</h2>
      {!evidence.length && <EmptyState text="本轮还没有检索证据。" />}
      {evidence.map((item, index) => (
        <article key={`${item.source}-${index}`} className="evidence-item">
          <strong>{item.source}</strong>
          <p>{item.content}</p>
          <small>{item.source_ref?.provenance}</small>
        </article>
      ))}
    </aside>
  );
}

function PersonaPage({
  token,
  personas,
  refresh,
  worldGroups,
  worldGroupsLoading,
  worldGroupError,
  refreshWorldGroups
}: {
  token: string;
  personas: Persona[];
  refresh: () => Promise<void>;
  worldGroups: PersonaWorldGroup[];
  worldGroupsLoading: boolean;
  worldGroupError: string;
  refreshWorldGroups: () => Promise<void>;
}) {
  const emptyForm = { name: "", description: "", persona_block: "", human_block: "", persona_type: "fictional_persona", consent_confirmed: false };
  const [form, setForm] = useState(emptyForm);
  const [generationDescription, setGenerationDescription] = useState("");
  const [generatedMemories, setGeneratedMemories] = useState<GeneratedMemoryDraft[]>([]);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const assignedPersonaIds = useMemo(() => {
    const ids = new Set<string>();
    for (const group of worldGroups) {
      for (const row of group.agents) ids.add(row.agent.persona_id);
    }
    return ids;
  }, [worldGroups]);
  const unassignedPersonas = useMemo(
    () => personas.filter((persona) => !assignedPersonaIds.has(persona.id)),
    [assignedPersonaIds, personas]
  );
  const showUnassignedPersonas = !worldGroupsLoading || worldGroups.length > 0;
  const generateDraft = async () => {
    if (!generationDescription.trim()) return;
    setGenerating(true);
    setError("");
    try {
      const draft = await api<PersonaDraft>("/personas/generate-draft", token, {
        method: "POST",
        body: JSON.stringify({ description: generationDescription, memory_count: 8 })
      });
      setForm({
        name: draft.name,
        description: draft.description,
        persona_block: draft.persona_block,
        human_block: draft.human_block,
        persona_type: "fictional_persona",
        consent_confirmed: false
      });
      setGeneratedMemories(draft.memories || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  };
  const create = async () => {
    setError("");
    try {
      if (generatedMemories.length) {
        await api<Persona>("/personas/generated", token, {
          method: "POST",
          body: JSON.stringify({
            name: form.name,
            description: form.description,
            persona_block: form.persona_block,
            human_block: form.human_block,
            memories: generatedMemories
              .filter((memory) => memory.content.trim())
              .map((memory) => ({
                content: memory.content,
                memory_type: memory.memory_type || "fact",
                confidence: Number.isFinite(memory.confidence) ? memory.confidence : 0.75
              }))
          })
        });
      } else {
        await api<Persona>("/personas", token, { method: "POST", body: JSON.stringify(form) });
      }
      setForm(emptyForm);
      setGenerationDescription("");
      setGeneratedMemories([]);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  };
  const init = async (id: string) => {
    await api<Persona>(`/personas/${id}/initialize-agent`, token, { method: "POST" });
    await refresh();
  };
  const renderPersonaRow = (persona: Persona | undefined, key: string, agent?: SimAgent) => (
    <article className="row-item" key={key}>
      <div>
        <strong>{persona?.name || agent?.name || "未知人格"}</strong>
        <p>{persona?.description || persona?.persona_block || (agent ? `儿童世界角色：${agent.name}` : "未填写描述")}</p>
        <small>
          {agent ? `${agentRoleLabel(agent)} · ` : ""}
          {persona?.persona_type || "未找到人格"} · {persona?.status || agent?.status || "unknown"} · {persona?.letta_agent_id || "未初始化"}
        </small>
      </div>
      <button onClick={() => persona && init(persona.id)} disabled={!persona}>
        <Bot size={16} />
        初始化
      </button>
    </article>
  );
  const updateGeneratedMemory = (index: number, changes: Partial<GeneratedMemoryDraft>) => {
    setGeneratedMemories((items) => items.map((item, itemIndex) => (itemIndex === index ? { ...item, ...changes } : item)));
  };
  const removeGeneratedMemory = (index: number) => {
    setGeneratedMemories((items) => items.filter((_, itemIndex) => itemIndex !== index));
  };
  return (
    <section className="grid-two">
      <div className="panel">
        <textarea
          className="large"
          placeholder="描述你想要的人格，例如背景、性格、说话方式、经历和边界"
          value={generationDescription}
          onChange={(event) => setGenerationDescription(event.target.value)}
        />
        <button className="primary" onClick={generateDraft} disabled={!generationDescription.trim() || generating}>
          <Sparkles size={16} />
          {generating ? "生成中" : "生成草稿"}
        </button>
        <div className="divider" />
        <h2>创建人格</h2>
        <input placeholder="名称" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        <textarea placeholder="描述" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
        <textarea placeholder="persona block" value={form.persona_block} onChange={(event) => setForm({ ...form, persona_block: event.target.value })} />
        <textarea placeholder="human block" value={form.human_block} onChange={(event) => setForm({ ...form, human_block: event.target.value })} />
        <select value={form.persona_type} onChange={(event) => setForm({ ...form, persona_type: event.target.value })}>
          <option value="fictional_persona">虚构人格</option>
          <option value="authorized_real_persona">授权真实人物</option>
        </select>
        <label className="checkline">
          <input type="checkbox" checked={form.consent_confirmed} onChange={(event) => setForm({ ...form, consent_confirmed: event.target.checked })} />
          已确认授权
        </label>
        {generatedMemories.length > 0 && (
          <div className="draft-memories">
            <div className="toolbar">
              <h2>生成历史记忆</h2>
              <button onClick={() => setGeneratedMemories([])}>清空</button>
            </div>
            {generatedMemories.map((memory, index) => (
              <div className="memory-draft" key={index}>
                <textarea value={memory.content} onChange={(event) => updateGeneratedMemory(index, { content: event.target.value })} />
                <div className="inline">
                  <select value={memory.memory_type} onChange={(event) => updateGeneratedMemory(index, { memory_type: event.target.value })}>
                    <option value="identity">identity</option>
                    <option value="fact">fact</option>
                    <option value="event">event</option>
                    <option value="preference">preference</option>
                    <option value="habit">habit</option>
                    <option value="goal">goal</option>
                  </select>
                  <input
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    value={memory.confidence}
                    onChange={(event) => updateGeneratedMemory(index, { confidence: Number(event.target.value) })}
                  />
                  <button onClick={() => removeGeneratedMemory(index)}>
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        {error && <p className="error">{error}</p>}
        <button className="primary" onClick={create} disabled={!form.name}>
          <Plus size={16} />
          创建
        </button>
      </div>
      <div className="panel">
        <div className="toolbar persona-list-toolbar">
          <h2>儿童世界角色</h2>
          <button onClick={() => void refreshWorldGroups()} disabled={worldGroupsLoading}>
            <RefreshCw size={16} />
            {worldGroupsLoading ? "刷新中" : "刷新分组"}
          </button>
        </div>
        {worldGroupError && <p className="error">{worldGroupError}</p>}
        {worldGroupsLoading && worldGroups.length === 0 && <EmptyState text="正在加载儿童世界角色。" />}
        {!worldGroupsLoading && worldGroups.length === 0 && <EmptyState text="还没有儿童世界。未绑定的人格会显示在下方。" />}
        <div className="world-persona-list">
          {worldGroups.map((group) => (
            <section className="world-persona-group" key={group.world.id}>
              <div className="world-group-heading">
                <div>
                  <h3>{group.world.name}</h3>
                  <small>
                    {group.world.status} · tick {group.world.tick_no} · {group.agents.length} 个角色
                  </small>
                </div>
              </div>
              {group.failed && <p className="error">这个儿童世界的角色加载失败。</p>}
              {!group.failed && group.agents.length === 0 && <EmptyState text="这个儿童世界还没有绑定角色。" />}
              {group.agents.map(({ agent, persona }) => renderPersonaRow(persona, `${group.world.id}-${agent.id}`, agent))}
            </section>
          ))}
          {showUnassignedPersonas && unassignedPersonas.length > 0 && (
            <section className="world-persona-group">
              <div className="world-group-heading">
                <div>
                  <h3>未绑定儿童世界</h3>
                  <small>{unassignedPersonas.length} 个人格</small>
                </div>
              </div>
              {unassignedPersonas.map((persona) => renderPersonaRow(persona, persona.id))}
            </section>
          )}
        </div>
      </div>
    </section>
  );
}

function MemoryPage({ token, personaId }: { token: string; personaId: string }) {
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [candidates, setCandidates] = useState<MemoryRecord[]>([]);
  const load = async () => {
    if (!personaId) return;
    setMemories(await api<MemoryRecord[]>(`/personas/${personaId}/memories`, token));
    setCandidates(await api<MemoryRecord[]>("/review/memory-candidates", token));
  };
  useEffect(() => {
    load().catch(console.error);
  }, [personaId]);
  const approve = async (id: string) => {
    await api<MemoryRecord>(`/review/memory-candidates/${id}/approve`, token, { method: "POST" });
    await load();
  };
  const remove = async (id: string) => {
    await api(`/personas/${personaId}/memories/${id}`, token, { method: "DELETE" });
    await load();
  };
  return (
    <section className="grid-two">
      <div className="panel">
        <div className="toolbar">
          <h2>长期记忆</h2>
          <button onClick={load}>
            <RefreshCw size={16} />
            刷新
          </button>
        </div>
        {memories.map((memory) => (
          <article className="row-item" key={memory.id}>
            <div>
              <strong>{memory.memory_type}</strong>
              <p>{memory.content}</p>
              <small>
                {memory.subject} · {memory.decision} · {memory.sensitivity}
              </small>
            </div>
            <button onClick={() => remove(memory.id)}>
              <Trash2 size={16} />
            </button>
          </article>
        ))}
      </div>
      <div className="panel">
        <h2>候选审核</h2>
        {candidates.map((memory) => (
          <article className="row-item" key={memory.id}>
            <div>
              <strong>{memory.memory_type}</strong>
              <p>{memory.content}</p>
              <small>{memory.sensitivity}</small>
            </div>
            <button onClick={() => approve(memory.id)}>
              <Check size={16} />
              通过
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}

function TimelinePage({ token, personaId }: { token: string; personaId: string }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Evidence[]>([]);
  const load = async () => {
    if (!personaId) return;
    setItems(await api<Evidence[]>(`/personas/${personaId}/timeline`, token));
  };
  const search = async () => {
    setItems(await api<Evidence[]>(`/personas/${personaId}/timeline/search`, token, { method: "POST", body: JSON.stringify({ query }) }));
  };
  useEffect(() => {
    load().catch(console.error);
  }, [personaId]);
  return (
    <section className="panel">
      <div className="toolbar">
        <input placeholder="搜索时间线" value={query} onChange={(event) => setQuery(event.target.value)} />
        <button onClick={search}>
          <Search size={16} />
          搜索
        </button>
      </div>
      {items.map((item, index) => (
        <article className="timeline-item" key={index}>
          <strong>{item.source_ref?.timestamp || item.source}</strong>
          <p>{item.content}</p>
          <small>{item.source_ref?.provenance}</small>
        </article>
      ))}
    </section>
  );
}

function DocumentsPage({ token, personaId }: { token: string; personaId: string }) {
  const [corpora, setCorpora] = useState<Corpus[]>([]);
  const [corpusName, setCorpusName] = useState("background");
  const [selectedCorpus, setSelectedCorpus] = useState("");
  const [filename, setFilename] = useState("note.txt");
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Evidence[]>([]);
  const load = async () => {
    if (!personaId) return;
    const data = await api<Corpus[]>(`/corpora?persona_id=${personaId}`, token);
    setCorpora(data);
    if (!selectedCorpus && data[0]) setSelectedCorpus(data[0].id);
  };
  useEffect(() => {
    load().catch(console.error);
  }, [personaId]);
  const createCorpus = async () => {
    const data = await api<Corpus>("/corpora", token, { method: "POST", body: JSON.stringify({ persona_id: personaId, name: corpusName, corpus_type: "background" }) });
    setCorpora([data, ...corpora]);
    setSelectedCorpus(data.id);
  };
  const upload = async () => {
    await api(`/corpora/${selectedCorpus}/documents`, token, { method: "POST", body: JSON.stringify({ filename, raw_text: text, content_type: "text/plain" }) });
    setText("");
  };
  const search = async () => {
    setResults(await api<Evidence[]>("/documents/search", token, { method: "POST", body: JSON.stringify({ persona_id: personaId, query, k: 5 }) }));
  };
  return (
    <section className="grid-two">
      <div className="panel">
        <h2>文档导入</h2>
        <div className="inline">
          <input value={corpusName} onChange={(event) => setCorpusName(event.target.value)} />
          <button onClick={createCorpus} disabled={!personaId}>
            <Plus size={16} />
            文档库
          </button>
        </div>
        <select value={selectedCorpus} onChange={(event) => setSelectedCorpus(event.target.value)}>
          <option value="">选择文档库</option>
          {corpora.map((corpus) => (
            <option key={corpus.id} value={corpus.id}>
              {corpus.name}
            </option>
          ))}
        </select>
        <input value={filename} onChange={(event) => setFilename(event.target.value)} />
        <textarea className="large" value={text} onChange={(event) => setText(event.target.value)} placeholder="粘贴 txt/md/json/csv 文本" />
        <button className="primary" onClick={upload} disabled={!selectedCorpus || !text.trim()}>
          <FileText size={16} />
          导入
        </button>
      </div>
      <div className="panel">
        <h2>文档检索</h2>
        <div className="inline">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="查询资料" />
          <button onClick={search}>
            <Search size={16} />
            搜索
          </button>
        </div>
        {results.map((item, index) => (
          <article className="evidence-item" key={index}>
            <strong>{item.source}</strong>
            <p>{item.content}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function EvalPage({ token, personaId }: { token: string; personaId: string }) {
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const run = async () => {
    const data = await api<{ results: Record<string, unknown> }>("/evals/run", token, { method: "POST", body: JSON.stringify({ persona_id: personaId || null }) });
    setResult(data.results);
  };
  return (
    <section className="panel">
      <button className="primary" onClick={run}>
        <Play size={16} />
        运行评测
      </button>
      {result && <pre>{JSON.stringify(result, null, 2)}</pre>}
    </section>
  );
}

function SettingsPage({ token }: { token: string }) {
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const load = async () => setHealth(await api<Record<string, unknown>>("/health", token));
  useEffect(() => {
    load().catch(console.error);
  }, []);
  return (
    <section className="panel">
      <div className="toolbar">
        <h2>服务状态</h2>
        <button onClick={load}>
          <Activity size={16} />
          刷新
        </button>
      </div>
      <div className="status-grid">
        <div>
          <ShieldCheck />
          单管理员认证
        </div>
        <div>
          <Database />
          PostgreSQL / SQLite
        </div>
        <div>
          <Brain />
          mem0 / Graphiti / LightRAG
        </div>
      </div>
      {health && <pre>{JSON.stringify(health, null, 2)}</pre>}
    </section>
  );
}
