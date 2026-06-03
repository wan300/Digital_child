import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Brain, Eye, KeyRound, Settings } from "lucide-react";
import { authApi, personaApi } from "./api";
import { ManagementConsole } from "./components/ManagementConsole";
import { ObserverConsole } from "./components/ObserverConsole";
import type { Persona } from "./types";

const navItems = [
  ["observer", "观察台", Eye],
  ["management", "管理区", Settings]
] as const;

type AppView = (typeof navItems)[number][0];
type AuthUser = { username: string; role: "admin" | "user" };

function isLoginRoute() {
  return window.location.pathname.replace(/\/+$/, "") === "/login";
}

function initialToken() {
  if (isLoginRoute()) {
    localStorage.removeItem("hm_token");
    return "";
  }
  return localStorage.getItem("hm_token") || "";
}

function useAuthSession() {
  const [token, setToken] = useState(initialToken);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(Boolean(token));

  const saveToken = useCallback((value: string, nextUser?: AuthUser) => {
    if (!value) return;
    localStorage.setItem("hm_token", value);
    setToken(value);
    if (nextUser) setUser(nextUser);
  }, []);

  const clearToken = useCallback(() => {
    localStorage.removeItem("hm_token");
    setToken("");
    setUser(null);
    setChecking(false);
  }, []);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setChecking(false);
      return;
    }
    let cancelled = false;
    setChecking(true);
    authApi
      .me(token)
      .then((currentUser) => {
        if (cancelled) return;
        setUser(currentUser);
        setChecking(false);
      })
      .catch(() => {
        if (cancelled) return;
        clearToken();
      });
    return () => {
      cancelled = true;
    };
  }, [clearToken, token]);

  return { token, user, checking, saveToken, clearToken };
}

function Login({ onLogin }: { onLogin: (token: string, user: AuthUser) => void }) {
  const [username, setUsername] = useState("user");
  const [password, setPassword] = useState("change-me-now");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const data = await authApi.login(username, password);
      const user = await authApi.me(data.access_token);
      onLogin(data.access_token, user);
      window.history.replaceState(null, "", "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <main className="login-shell">
      <form className="login-panel" onSubmit={submit}>
        <div className="brand-row">
            <Brain />
            <div>
            <h1>儿童成长观察台</h1>
            <p>Letta + mem0 + Graphiti + LightRAG</p>
          </div>
        </div>
        <label>
          账号
          <input value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          密码
          <input value={password} type="password" onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="primary" type="submit" disabled={submitting}>
          <KeyRound size={18} />
          登录
        </button>
      </form>
    </main>
  );
}

export default function App() {
  const { token, user, checking, saveToken, clearToken } = useAuthSession();
  const [view, setView] = useState<AppView>("observer");
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersonaId, setSelectedPersonaId] = useState("");
  const [notice, setNotice] = useState("");
  const canManage = user?.role === "admin";
  const visibleNavItems = canManage ? navItems : navItems.filter(([id]) => id !== "management");

  const refreshPersonas = async () => {
    if (!token || !canManage) {
      setPersonas([]);
      setSelectedPersonaId("");
      return;
    }
    const data = await personaApi.list(token);
    setPersonas(data);
    setSelectedPersonaId((current) => current || data[0]?.id || "");
  };

  useEffect(() => {
    refreshPersonas().catch((err) => setNotice(err instanceof Error ? err.message : "加载人格失败"));
  }, [canManage, token]);

  useEffect(() => {
    if (!canManage && view === "management") setView("observer");
  }, [canManage, view]);

  const logout = async () => {
    if (token) {
      try {
        await authApi.logout(token);
      } catch {
        // Clear local auth state even if the token is already invalid on the server.
      }
    }
    clearToken();
    window.history.replaceState(null, "", "/login");
  };

  if (!token) return <Login onLogin={saveToken} />;
  if (checking && !user) {
    return (
      <main className="login-shell">
        <div className="login-panel">
          <div className="brand-row">
            <Brain />
            <div>
              <h1>Child Growth OS</h1>
              <p>正在校验登录状态</p>
            </div>
          </div>
        </div>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-title">
          <Brain />
          <span>Child Growth OS</span>
        </div>
        <div className="auth-status">
          <span>登录状态</span>
          <strong>{user ? `已登录：${user.username}（${user.role === "admin" ? "管理员" : "普通用户"}）` : "正在校验"}</strong>
        </div>
        <nav>
          {visibleNavItems.map(([id, label, Icon]) => (
            <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>
              <Icon size={18} />
              {label}
            </button>
          ))}
        </nav>
        <button className="ghost" onClick={() => void logout()}>
          退出
        </button>
      </aside>
      <main className="content">
        {view === "observer" && <ObserverConsole token={token} personas={personas} refreshPersonas={refreshPersonas} />}
        {canManage && view === "management" && (
          <ManagementConsole
            token={token}
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
