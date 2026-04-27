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

export type PanelId =
  | "status"
  | "chat"
  | "logs"
  | "profiles"
  | "messages"
  | "traces";

export const ALL_PANELS: PanelId[] = [
  "status",
  "chat",
  "logs",
  "messages",
  "traces",
  "profiles",
];

/** Extract all panel names from a regular-layout Layout tree.
 *
 * regular-layout 0.4 renamed the node types: `child-panel`→`tab-layout`
 * (with `tabs` instead of `child`) and `split-panel`→`split-layout`. We
 * accept both for forward/backward compat — getting this wrong means we
 * detect "no panels", which triggers the empty-layout recovery branch
 * and causes either an infinite re-insert loop or duplicate tabs.
 */
export function extractPanelNames(layout: unknown): Set<string> {
  const names = new Set<string>();
  function walk(node: unknown) {
    if (!node || typeof node !== "object") return;
    const n = node as Record<string, unknown>;
    const type = n.type;
    if (type === "tab-layout" || type === "child-panel") {
      const tabs = (n.tabs ?? n.child) as unknown;
      if (Array.isArray(tabs)) {
        for (const t of tabs) {
          if (typeof t === "string") names.add(t);
        }
      } else if (typeof tabs === "string") {
        names.add(tabs);
      }
    } else if (type === "split-layout" || type === "split-panel") {
      const children = n.children;
      if (Array.isArray(children)) {
        for (const c of children) walk(c);
      }
    }
  }
  walk(layout);
  return names;
}

/** Walk layout tree and set `selected` so the named panel is the active tab. */
export function selectPanelInLayout(layout: unknown, name: string): boolean {
  if (!layout || typeof layout !== "object") return false;
  const n = layout as Record<string, unknown>;
  const type = n.type;
  if (type === "tab-layout" || type === "child-panel") {
    const tabs = (n.tabs ?? n.child) as unknown;
    if (Array.isArray(tabs)) {
      const idx = (tabs as string[]).indexOf(name);
      if (idx >= 0) {
        n.selected = idx;
        return true;
      }
    } else if (tabs === name) {
      return true;
    }
  } else if (type === "split-layout" || type === "split-panel") {
    const children = n.children;
    if (Array.isArray(children)) {
      for (const c of children) {
        if (selectPanelInLayout(c, name)) return true;
      }
    }
  }
  return false;
}

/** Returns true if the named panel is the currently-visible (selected) tab
 *  in its tab-layout group.  A panel that exists in the tree but sits behind
 *  another tab is *not* visible. */
export function isPanelVisible(layout: unknown, name: string): boolean {
  if (!layout || typeof layout !== "object") return false;
  const n = layout as Record<string, unknown>;
  const type = n.type;
  if (type === "tab-layout" || type === "child-panel") {
    const tabs = (n.tabs ?? n.child) as unknown;
    if (Array.isArray(tabs)) {
      const idx = (tabs as string[]).indexOf(name);
      if (idx < 0) return false;
      const selected = typeof n.selected === "number" ? n.selected : 0;
      return idx === selected;
    }
    return tabs === name;
  } else if (type === "split-layout" || type === "split-panel") {
    const children = n.children;
    if (Array.isArray(children)) {
      for (const c of children) {
        if (isPanelVisible(c, name)) return true;
      }
    }
  }
  return false;
}

/** AgentInspector is special — it needs a param and opens on top of everything. */
interface InspectorState {
  agentId: string;
}

// ── Hash Router (deep-links only) ──────────────────────────

export function parseHash(hash: string): {
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

    // Track consecutive empty layout updates so we break out of any
    // pathological loop where restoring a stale localStorage layout fails
    // to register any panels and we keep re-inserting "status" forever.
    // (Symptom: Chrome RESULT_CODE_HUNG on tab load.)
    let consecutiveEmpty = 0;

    const handler = (e: CustomEvent) => {
      const names = extractPanelNames(e.detail);
      setActivePanels(names);
      try {
        localStorage.setItem("langley-layout", JSON.stringify(e.detail));
      } catch {
        /* ignore */
      }
      // If all panels were closed, re-open the status panel — but only if
      // we haven't just done so unsuccessfully.  Repeated empty updates
      // mean either the saved layout uses a schema we no longer recognize
      // or insertPanel is no-oping; either way, bail out and reset.
      if (names.size === 0) {
        consecutiveEmpty += 1;
        if (consecutiveEmpty >= 3) {
          try {
            localStorage.removeItem("langley-layout");
          } catch {
            /* ignore */
          }
          return;
        }
        // Defensively check whether status is already present (the
        // detected-empty state may be a false negative due to a schema
        // mismatch); if so, do nothing and let consecutiveEmpty trigger
        // the bail-out rather than racking up duplicate tabs.
        const statusExists = el.getPanel
          ? el.getPanel("status") != null
          : false;
        if (!statusExists) {
          el.insertPanel("status");
        }
      } else {
        consecutiveEmpty = 0;
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
          // Only restore if the saved layout actually contains panels we
          // can recognize.  A layout we can't parse would otherwise fire
          // an empty regular-layout-update which the handler responds to
          // by inserting "status", which fires another event, etc.
          if (extractPanelNames(parsed).size > 0) {
            el.restore(parsed);
            restored = true;
          } else {
            localStorage.removeItem("langley-layout");
          }
        }
      } catch {
        /* fall through to default */
      }

      if (!restored) {
        // Default: insert panels from hash route (or just status).
        // Guard with getPanel so we never create duplicate tabs if the
        // user navigates and the effect re-runs.
        for (const p of initialRoute.panels) {
          const exists = el.getPanel ? el.getPanel(p) != null : false;
          if (!exists) el.insertPanel(p);
        }
      }
    }

    return () => {
      el.removeEventListener("regular-layout-update", handler as EventListener);
    };
  }, []);

  // Workaround for regular-layout 0.4 bug: when a tab drag is cancelled
  // (escape, scroll, lost pointer capture, etc.), the library's overlay
  // controller calls `clear(null, ...)` which early-returns BEFORE removing
  // the `.overlay` CSS class.  The result is a "ghost" frame stuck on the
  // page with dashed-border styling and hidden contents until the next
  // successful drag.  We mop up by stripping `.overlay` from every frame
  // child after pointerup/pointercancel/lostpointercapture.  Running on
  // pointerup is also safe: the lib's handler runs first synchronously
  // and our removal is a no-op when the drag completed cleanly.
  useEffect(() => {
    const el = layoutRef.current;
    if (!el) return;

    const cleanup = () => {
      // setTimeout(0) so the library's own clear() runs first.
      setTimeout(() => {
        if (!layoutRef.current) return;
        const frames = layoutRef.current.querySelectorAll(":scope > .overlay");
        frames.forEach((f) => f.classList.remove("overlay"));
      }, 0);
    };

    const events = ["pointerup", "pointercancel", "lostpointercapture"];
    for (const e of events) {
      window.addEventListener(e, cleanup, { capture: true });
    }
    window.addEventListener("blur", cleanup);

    return () => {
      for (const e of events) {
        window.removeEventListener(e, cleanup, {
          capture: true,
        } as EventListenerOptions);
      }
      window.removeEventListener("blur", cleanup);
    };
  }, []);

  const togglePanel = useCallback((id: PanelId) => {
    const el = layoutRef.current;
    if (!el) return;
    // Use the layout's own state as the source of truth, not React's
    // possibly-stale activePanels.  Inserting a panel that already exists
    // creates a duplicate tab (regular-layout doesn't dedupe by name).
    const exists = el.getPanel ? el.getPanel(id) != null : false;
    if (!exists) {
      el.insertPanel(id);
      return;
    }
    // Panel exists.  If it's hidden behind another tab, foreground it
    // instead of closing.  Only close when it's already the visible tab.
    const tree = el.save();
    if (tree && !isPanelVisible(tree, id) && selectPanelInLayout(tree, id)) {
      el.restore(tree);
      return;
    }
    el.removePanel(id);
  }, []);

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

  const handleNavigateChat = useCallback((agentId: string) => {
    setChatInitialAgent(agentId);
    const el = layoutRef.current;
    if (!el) return;
    const exists = el.getPanel ? el.getPanel("chat") != null : false;
    if (exists) {
      // Panel exists — foreground it if it's behind another tab
      const tree = el.save();
      if (tree && selectPanelInLayout(tree, "chat")) {
        el.restore(tree);
      }
    } else {
      el.insertPanel("chat");
    }
  }, []);

  const handleNavigateInspect = useCallback((agentId: string) => {
    setInspector({ agentId });
    const el = layoutRef.current;
    if (!el) return;
    const exists = el.getPanel ? el.getPanel("inspector") != null : false;
    if (!exists) {
      el.insertPanel("inspector");
      return;
    }
    // Already in the layout — bring to foreground if it's hidden behind another tab.
    const tree = el.save();
    if (tree && !isPanelVisible(tree, "inspector")) {
      if (selectPanelInLayout(tree, "inspector")) {
        el.restore(tree);
      }
    }
  }, []);

  // Sync inspector state → panel presence: removing the panel via the
  // titlebar 'x' fires regular-layout-update which clears it from
  // activePanels; we mirror that into our inspector React state.
  useEffect(() => {
    if (!inspector) return;
    if (!activePanels.has("inspector")) {
      setInspector(undefined);
    }
  }, [activePanels, inspector]);

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
        <h1>hq</h1>
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

          {/* @ts-expect-error regular-layout-frame is a web component */}
          <regular-layout-frame
            name="inspector"
            data-testid="panel-agent-inspector"
          >
            {inspector ? (
              <AgentInspector
                agentId={inspector.agentId}
                onBack={() => {
                  setInspector(undefined);
                  layoutRef.current?.removePanel("inspector");
                }}
                onAction={() => onAgentsChanged()}
              />
            ) : (
              <div className="langley-empty">No agent selected.</div>
            )}
          </regular-layout-frame>
        </regular-layout>
      </main>
    </div>
  );
}
