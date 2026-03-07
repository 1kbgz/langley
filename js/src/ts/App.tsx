import { useState, useEffect, useCallback, useRef } from "react";
import { listAgents, fetchActivity } from "./api.ts";
import type { AgentInfo, AuditEntryInfo } from "./api.ts";
import { LangleyWsClient } from "./ws.ts";
import type { AgentSummary } from "./components/types.ts";
import { StatusTab } from "./components/StatusTab.tsx";
import { ChatTab } from "./components/ChatTab.tsx";
import { LogsTab } from "./components/LogsTab.tsx";
import { ProfilesTab } from "./components/ProfilesTab.tsx";

// Re-export for test compatibility
export type { AgentSummary } from "./components/types.ts";
export type { AgentStatus } from "./components/types.ts";
export interface DashboardState {
  agents: AgentSummary[];
  connected: boolean;
  error: string | null;
}

function toSummary(info: AgentInfo): AgentSummary {
  const now = Date.now() / 1000;
  return {
    id: info.agent_id,
    name: info.profile_name,
    status: info.status as AgentSummary["status"],
    profile: info.profile_name,
    tenant_id: info.tenant_id,
    uptime_seconds: info.started_at ? now - info.started_at : 0,
  };
}

// ── Hash Router ────────────────────────────────────────────

type Tab = "status" | "chat" | "logs" | "profiles";

function parseHash(hash: string): { tab: Tab; param?: string } {
  const cleaned = hash.replace(/^#\/?/, "");
  const [segment, ...rest] = cleaned.split("/");
  const tab = (["status", "chat", "logs", "profiles"].includes(segment) ? segment : "status") as Tab;
  return { tab, param: rest.join("/") || undefined };
}

function useHash(): { tab: Tab; param?: string } {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const handler = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  return route;
}

function navigate(tab: Tab, param?: string) {
  window.location.hash = param ? `#/${tab}/${param}` : `#/${tab}`;
}

// ── Theme ──────────────────────────────────────────────────

type Theme = "dark" | "light";

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem("langley-theme") as Theme) ?? "dark";
    } catch {
      return "dark";
    }
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("langley-theme", theme);
    } catch { /* localStorage not available */ }
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return [theme, toggle];
}

// ── Main App ───────────────────────────────────────────────

const TAB_LABELS: { id: Tab; label: string }[] = [
  { id: "status", label: "Status" },
  { id: "chat", label: "Chat" },
  { id: "logs", label: "Logs" },
  { id: "profiles", label: "Profiles" },
];

export function App() {
  const { tab, param } = useHash();
  const [theme, toggleTheme] = useTheme();

  const [state, setState] = useState<DashboardState>({
    agents: [],
    connected: false,
    error: null,
  });
  const [activity, setActivity] = useState<AuditEntryInfo[]>([]);
  const wsRef = useRef<LangleyWsClient | null>(null);

  const fetchAgents = useCallback(async () => {
    try {
      const data = await listAgents();
      setState((prev) => ({
        ...prev,
        agents: data.map(toSummary),
        error: null,
      }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        error: err instanceof Error ? err.message : "Failed to fetch agents",
      }));
    }
  }, []);

  const refreshActivity = useCallback(async () => {
    try {
      const events = await fetchActivity(30);
      setActivity(events);
    } catch { /* non-critical */ }
  }, []);

  const onAgentsChanged = useCallback(() => {
    fetchAgents();
    refreshActivity();
  }, [fetchAgents, refreshActivity]);

  useEffect(() => {
    fetchAgents();
    refreshActivity();

    const interval = setInterval(() => {
      fetchAgents();
      refreshActivity();
    }, 5000);

    const ws = new LangleyWsClient();
    wsRef.current = ws;

    ws.onConnect = () => setState((prev) => ({ ...prev, connected: true }));
    ws.onDisconnect = () => setState((prev) => ({ ...prev, connected: false }));
    ws.onError = (msg) => setState((prev) => ({ ...prev, error: msg }));

    ws.subscribe("agent.status", () => {
      fetchAgents();
      refreshActivity();
    });

    ws.connect();

    return () => {
      clearInterval(interval);
      ws.disconnect();
    };
  }, [fetchAgents, refreshActivity]);

  const handleNavigateChat = useCallback((agentId: string) => {
    navigate("chat", agentId);
  }, []);

  return (
    <div className="langley-app" data-testid="langley-app">
      <header className="langley-header">
        <h1>Langley</h1>
        <nav className="langley-nav" data-testid="tab-nav">
          {TAB_LABELS.map(({ id, label }) => (
            <a
              key={id}
              href={`#/${id}`}
              className={`langley-nav-tab${tab === id ? " active" : ""}`}
              data-testid={`tab-${id}`}
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="langley-header-right">
          <button
            className="langley-btn langley-theme-toggle"
            onClick={toggleTheme}
            data-testid="theme-toggle"
            title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? "☀" : "☾"}
          </button>
          <span
            className={`langley-connection-status${state.connected ? " connected" : ""}`}
            data-testid="connection-status"
          >
            {state.connected ? "Connected" : "Disconnected"}
          </span>
        </div>
      </header>
      <main className="langley-main">
        {state.error && (
          <div className="langley-error" data-testid="error-banner">
            {state.error}
          </div>
        )}
        {tab === "status" && (
          <StatusTab
            agents={state.agents}
            activity={activity}
            onAgentsChanged={onAgentsChanged}
            onNavigateChat={handleNavigateChat}
          />
        )}
        {tab === "chat" && (
          <ChatTab agents={state.agents} initialAgentId={param} />
        )}
        {tab === "logs" && (
          <LogsTab agents={state.agents} />
        )}
        {tab === "profiles" && (
          <ProfilesTab />
        )}
      </main>
    </div>
  );
}
