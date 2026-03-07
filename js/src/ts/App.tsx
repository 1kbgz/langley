import { useState, useEffect, useCallback, useRef } from "react";
import {
  listAgents,
  fetchActivity,
  stopAgent,
  killAgent,
  restartAgent,
} from "./api.ts";
import type { AgentInfo, AuditEntryInfo } from "./api.ts";
import { LangleyWsClient } from "./ws.ts";
import type { AgentSummary } from "./components/types.ts";
import { StatusTab } from "./components/StatusTab.tsx";
import { ChatTab } from "./components/ChatTab.tsx";
import { LogsTab } from "./components/LogsTab.tsx";
import { ProfilesTab } from "./components/ProfilesTab.tsx";
import { AgentInspector } from "./components/AgentInspector.tsx";
import { MessageInspectorTab } from "./components/MessageInspectorTab.tsx";
import { TraceTab } from "./components/TraceTab.tsx";
import type { RegularLayout } from "regular-layout";
import "regular-layout";

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

// ── Layout helpers ─────────────────────────────────────────

type PanelId = "status" | "chat" | "logs" | "profiles" | "messages" | "traces";

const ALL_PANELS: PanelId[] = [
  "status",
  "chat",
  "logs",
  "messages",
  "traces",
  "profiles",
];

/** Extract all panel names from a regular-layout Layout tree. */
function extractPanelNames(layout: unknown): Set<string> {
  const names = new Set<string>();
  function walk(node: unknown) {
    if (!node || typeof node !== "object") return;
    const n = node as Record<string, unknown>;
    if (n.type === "child-panel" && Array.isArray(n.tabs)) {
      for (const t of n.tabs) names.add(t as string);
    } else if (n.type === "split-panel" && Array.isArray(n.children)) {
      for (const c of n.children) walk(c);
    }
  }
  walk(layout);
  return names;
}

/** AgentInspector is special — it needs a param and opens on top of everything. */
interface InspectorState {
  agentId: string;
}

// ── Hash Router (deep-links only) ──────────────────────────

function parseHash(hash: string): {
  panels: PanelId[];
  inspector?: InspectorState;
  chatAgentId?: string;
} {
  const cleaned = hash.replace(/^#\/?/, "");
  const segments = cleaned.split("/").filter(Boolean);
  if (segments[0] === "agent" && segments[1]) {
    return { panels: ["status"], inspector: { agentId: segments[1] } };
  }
  if (segments[0] === "chat") {
    return { panels: ["chat"], chatAgentId: segments[1] };
  }
  const panel = ALL_PANELS.find((p) => p === segments[0]);
  return { panels: panel ? [panel] : ["status"] };
}

function useHash() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const handler = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  return route;
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
    } catch {
      /* localStorage not available */
    }
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return [theme, toggle];
}

// ── Nav panel definitions ──────────────────────────────────

const PANEL_LABELS: { id: PanelId; label: string }[] = [
  { id: "status", label: "Status" },
  { id: "chat", label: "Chat" },
  { id: "logs", label: "Logs" },
  { id: "messages", label: "Messages" },
  { id: "traces", label: "Traces" },
  { id: "profiles", label: "Profiles" },
];

// ── Main App ───────────────────────────────────────────────

export function App() {
  const initialRoute = useHash();
  const [theme, toggleTheme] = useTheme();

  const [state, setState] = useState<DashboardState>({
    agents: [],
    connected: false,
    error: null,
  });
  const [activity, setActivity] = useState<AuditEntryInfo[]>([]);
  const wsRef = useRef<LangleyWsClient | null>(null);

  // ── Layout state ─────────────────────────────────────────
  const layoutRef = useRef<RegularLayout | null>(null);
  const [activePanels, setActivePanels] = useState<Set<string>>(
    () => new Set(initialRoute.panels),
  );
  const [inspector, setInspector] = useState<InspectorState | undefined>(
    initialRoute.inspector,
  );
  const [chatInitialAgent, setChatInitialAgent] = useState<string | undefined>(
    initialRoute.chatAgentId,
  );
  const layoutInitedRef = useRef(false);

  // Sync regular-layout events → React state
  useEffect(() => {
    const el = layoutRef.current;
    if (!el) return;

    const handler = (e: CustomEvent) => {
      const names = extractPanelNames(e.detail);
      setActivePanels(names);
      try {
        localStorage.setItem("langley-layout", JSON.stringify(e.detail));
      } catch {
        /* ignore */
      }
      // If all panels were closed, re-open the status panel
      if (names.size === 0) {
        el.insertPanel("status");
      }
    };

    el.addEventListener("regular-layout-update", handler as EventListener);

    // Initialize layout: restore from localStorage or use default
    if (!layoutInitedRef.current) {
      layoutInitedRef.current = true;
      let restored = false;
      try {
        const saved = localStorage.getItem("langley-layout");
        if (saved) {
          const parsed = JSON.parse(saved);
          el.restore(parsed);
          restored = true;
        }
      } catch {
        /* fall through to default */
      }

      if (!restored) {
        // Default: insert panels from hash route (or just status)
        for (const p of initialRoute.panels) {
          el.insertPanel(p);
        }
      }
    }

    return () => {
      el.removeEventListener("regular-layout-update", handler as EventListener);
    };
  }, []);

  const togglePanel = useCallback(
    (id: PanelId) => {
      const el = layoutRef.current;
      if (!el) return;
      if (activePanels.has(id)) {
        el.removePanel(id);
      } else {
        el.insertPanel(id);
      }
    },
    [activePanels],
  );

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
    } catch {
      /* non-critical */
    }
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

  const handleNavigateChat = useCallback(
    (agentId: string) => {
      setChatInitialAgent(agentId);
      const el = layoutRef.current;
      if (el && !activePanels.has("chat")) {
        el.insertPanel("chat");
      }
    },
    [activePanels],
  );

  const handleNavigateInspect = useCallback((agentId: string) => {
    setInspector({ agentId });
  }, []);

  const handleBulkAction = useCallback(
    async (agentIds: string[], action: "stop" | "kill" | "restart") => {
      for (const id of agentIds) {
        try {
          if (action === "stop") await stopAgent(id);
          else if (action === "kill") await killAgent(id);
          else if (action === "restart") await restartAgent(id);
        } catch {
          /* best-effort */
        }
      }
      onAgentsChanged();
    },
    [onAgentsChanged],
  );

  return (
    <div className="langley-app" data-testid="langley-app">
      <header className="langley-header">
        <h1>Langley</h1>
        <nav className="langley-nav" data-testid="tab-nav">
          {PANEL_LABELS.map(({ id, label }) => (
            <button
              key={id}
              className={`langley-nav-tab${activePanels.has(id) ? " active" : ""}`}
              data-testid={`tab-${id}`}
              onClick={() => togglePanel(id)}
            >
              {label}
            </button>
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

        {/* @ts-expect-error regular-layout is a web component */}
        <regular-layout ref={layoutRef} data-testid="layout-container">
          <regular-layout-frame name="status" data-testid="panel-status">
            <StatusTab
              agents={state.agents}
              activity={activity}
              onAgentsChanged={onAgentsChanged}
              onNavigateChat={handleNavigateChat}
              onNavigateInspect={handleNavigateInspect}
              onBulkAction={handleBulkAction}
            />
          </regular-layout-frame>

          {/* @ts-expect-error regular-layout-frame is a web component */}
          <regular-layout-frame name="chat" data-testid="panel-chat">
            <ChatTab
              agents={state.agents}
              initialAgentId={chatInitialAgent}
              wsClient={wsRef.current}
            />
          </regular-layout-frame>

          {/* @ts-expect-error regular-layout-frame is a web component */}
          <regular-layout-frame name="logs" data-testid="panel-logs">
            <LogsTab agents={state.agents} />
          </regular-layout-frame>

          {/* @ts-expect-error regular-layout-frame is a web component */}
          <regular-layout-frame name="messages" data-testid="panel-messages">
            <MessageInspectorTab />
          </regular-layout-frame>

          {/* @ts-expect-error regular-layout-frame is a web component */}
          <regular-layout-frame name="traces" data-testid="panel-traces">
            <TraceTab agents={state.agents} />
          </regular-layout-frame>

          {/* @ts-expect-error regular-layout-frame is a web component */}
          <regular-layout-frame name="profiles" data-testid="panel-profiles">
            <ProfilesTab />
          </regular-layout-frame>
        </regular-layout>

        {/* Agent inspector — modal overlay on top of everything */}
        {inspector && (
          <div
            className="langley-overlay-inspector"
            data-testid="panel-agent-inspector"
          >
            <div className="langley-overlay-header">
              <span className="langley-overlay-title">Agent Inspector</span>
              <button
                className="langley-btn langley-overlay-close"
                onClick={() => setInspector(undefined)}
                data-testid="close-inspector"
              >
                &times;
              </button>
            </div>
            <div className="langley-overlay-body">
              <AgentInspector
                agentId={inspector.agentId}
                onBack={() => setInspector(undefined)}
                onAction={() => onAgentsChanged()}
              />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
