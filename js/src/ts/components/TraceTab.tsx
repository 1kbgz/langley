import { useState, useEffect, useCallback } from "react";
import { queryAudit, listAgents } from "../api.ts";
import type { AuditEntryInfo, AgentInfo } from "../api.ts";
import type { AgentSummary } from "./types.ts";

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString();
}

function formatDateTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

interface OperationEntry {
  id: string;
  agent_id: string;
  agent_name: string;
  event_type: string;
  timestamp: number;
  payload: Record<string, unknown>;
}

const EVENT_TYPE_COLORS: Record<string, string> = {
  "agent.started": "var(--green)",
  "agent.stopped": "var(--gray)",
  "agent.killed": "var(--red)",
  "agent.exited": "var(--gray)",
  "agent.errored": "var(--red)",
  "agent.auto_restarted": "var(--yellow)",
  "agent.heartbeat_timeout": "var(--red)",
  "agent.launch_failed": "var(--red)",
  "agent.stop_requested": "var(--yellow)",
  "agent.force_killed_after_timeout": "var(--red)",
};

export function TraceTab({ agents }: { agents: AgentSummary[] }) {
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [eventFilter, setEventFilter] = useState<string>("all");
  const [operations, setOperations] = useState<OperationEntry[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);

  // Build a name map from agents
  const agentNameMap: Record<string, string> = {};
  for (const a of agents) {
    agentNameMap[a.id] = a.name;
  }

  const fetchOperations = useCallback(async () => {
    setLoading(true);
    try {
      const opts: {
        agent_id?: string;
        event_type?: string;
        limit?: number;
      } = { limit: 500 };
      if (selectedAgent) opts.agent_id = selectedAgent;
      if (eventFilter !== "all") opts.event_type = eventFilter;

      const entries = await queryAudit("default", opts);
      setOperations(
        entries.map((e) => ({
          id: e.id,
          agent_id: e.agent_id,
          agent_name:
            agentNameMap[e.agent_id] ?? e.agent_id?.slice(0, 8) ?? "unknown",
          event_type: e.event_type,
          timestamp: e.timestamp,
          payload: e.payload,
        })),
      );
    } catch {
      /* non-critical */
    }
    setLoading(false);
  }, [selectedAgent, eventFilter]);

  useEffect(() => {
    fetchOperations();
    const interval = setInterval(fetchOperations, 5000);
    return () => clearInterval(interval);
  }, [fetchOperations]);

  // Compute stats from operations
  const stats = {
    total: operations.length,
    launches: operations.filter((o) => o.event_type === "agent.started").length,
    errors: operations.filter(
      (o) =>
        o.event_type.includes("error") ||
        o.event_type.includes("failed") ||
        o.event_type.includes("killed"),
    ).length,
    restarts: operations.filter((o) => o.event_type === "agent.auto_restarted")
      .length,
  };

  const filteredOps = operations.filter((o) => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (
      o.event_type.toLowerCase().includes(s) ||
      o.agent_name.toLowerCase().includes(s) ||
      o.agent_id.toLowerCase().includes(s) ||
      JSON.stringify(o.payload).toLowerCase().includes(s)
    );
  });

  // Unique event types for filter
  const eventTypes = [...new Set(operations.map((o) => o.event_type))].sort();

  return (
    <div className="langley-trace-tab" data-testid="trace-tab">
      {/* Stats summary */}
      <div className="langley-trace-stats">
        <div className="langley-trace-stat-card">
          <span className="langley-trace-stat-value">{stats.total}</span>
          <span className="langley-trace-stat-label">Total Events</span>
        </div>
        <div className="langley-trace-stat-card">
          <span
            className="langley-trace-stat-value"
            style={{ color: "var(--green)" }}
          >
            {stats.launches}
          </span>
          <span className="langley-trace-stat-label">Launches</span>
        </div>
        <div className="langley-trace-stat-card">
          <span
            className="langley-trace-stat-value"
            style={{ color: "var(--red)" }}
          >
            {stats.errors}
          </span>
          <span className="langley-trace-stat-label">Errors/Kills</span>
        </div>
        <div className="langley-trace-stat-card">
          <span
            className="langley-trace-stat-value"
            style={{ color: "var(--yellow)" }}
          >
            {stats.restarts}
          </span>
          <span className="langley-trace-stat-label">Auto-Restarts</span>
        </div>
      </div>

      {/* Controls */}
      <div className="langley-logs-controls">
        <label htmlFor="trace-agent-select">Agent: </label>
        <select
          id="trace-agent-select"
          value={selectedAgent}
          onChange={(e) => setSelectedAgent(e.target.value)}
          data-testid="trace-agent-select"
        >
          <option value="">All Agents</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.id.slice(0, 8)})
            </option>
          ))}
        </select>

        <label htmlFor="trace-event-filter">Event: </label>
        <select
          id="trace-event-filter"
          value={eventFilter}
          onChange={(e) => setEventFilter(e.target.value)}
          data-testid="trace-event-filter"
        >
          <option value="all">All Events</option>
          {eventTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search events..."
          className="langley-logs-search"
          data-testid="trace-search"
        />
      </div>

      {/* Operation timeline */}
      <div className="langley-trace-timeline" data-testid="trace-timeline">
        {loading && operations.length === 0 ? (
          <div className="langley-empty">Loading...</div>
        ) : filteredOps.length === 0 ? (
          <div className="langley-empty">No events found.</div>
        ) : (
          filteredOps.map((op) => (
            <div
              key={op.id}
              className="langley-trace-entry"
              data-testid={`trace-${op.id}`}
            >
              <div
                className="langley-trace-dot"
                style={{
                  backgroundColor:
                    EVENT_TYPE_COLORS[op.event_type] ?? "var(--text-muted)",
                }}
              />
              <div className="langley-trace-content">
                <div className="langley-trace-header">
                  <span className="langley-trace-time">
                    {formatDateTime(op.timestamp)}
                  </span>
                  <span className="langley-trace-event-type">
                    {op.event_type}
                  </span>
                  <span className="langley-trace-agent">{op.agent_name}</span>
                </div>
                {Object.keys(op.payload).length > 0 && (
                  <div className="langley-trace-payload">
                    {Object.entries(op.payload).map(([k, v]) => (
                      <span key={k} className="langley-trace-kv">
                        <strong>{k}:</strong>{" "}
                        {typeof v === "string" ? v : JSON.stringify(v)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
