import { useCallback, useEffect, useState } from "react";
import { Brain, Eye, Settings } from "lucide-react";
import { personaApi } from "./api";
import { ManagementConsole } from "./components/ManagementConsole";
import { ObserverConsole } from "./components/ObserverConsole";
import type { Persona } from "./types";

const AUTH_DISABLED_TOKEN = "";

const navItems = [
  ["observer", "观察台", Eye],
  ["management", "管理区", Settings]
] as const;

type AppView = (typeof navItems)[number][0];

export default function App() {
  const [view, setView] = useState<AppView>("observer");
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersonaId, setSelectedPersonaId] = useState("");
  const [notice, setNotice] = useState("");

  const refreshPersonas = useCallback(async () => {
    const data = await personaApi.list(AUTH_DISABLED_TOKEN);
    setPersonas(data);
    setSelectedPersonaId((current) => current || data[0]?.id || "");
    setNotice("");
  }, []);

  useEffect(() => {
    refreshPersonas().catch((err) => setNotice(err instanceof Error ? err.message : "加载人格失败"));
  }, [refreshPersonas]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-title">
          <Brain />
          <span>Child Growth OS</span>
        </div>
        <div className="auth-status">
          <span>身份核验</span>
          <strong>已关闭，当前为管理员权限</strong>
        </div>
        <nav>
          {navItems.map(([id, label, Icon]) => (
            <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>
              <Icon size={18} />
              {label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="content">
        {view === "observer" && (
          <ObserverConsole token={AUTH_DISABLED_TOKEN} personas={personas} refreshPersonas={refreshPersonas} />
        )}
        {view === "management" && (
          <ManagementConsole
            token={AUTH_DISABLED_TOKEN}
            personas={personas}
            selectedPersonaId={selectedPersonaId}
            setSelectedPersonaId={setSelectedPersonaId}
            refreshPersonas={refreshPersonas}
            notice={notice}
          />
        )}
      </main>
    </div>
  );
}
