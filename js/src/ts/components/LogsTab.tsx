import { useState, useEffect, useRef, useCallback } from "react";
import { queryMessages } from "../api.ts";
import type { AgentSummary } from "./types.ts";

interface LogEntry {
  id: string;
  timestamp: number;
  level: string;
  message: string;
}

function parseLogEntry(msg: { id: string; body: unknown; timestamp: number }): LogEntry {
  const body = msg.body as Record<string, unknown>;
  return {
    id: msg.id,
    timestamp: (body.timestamp as number) ?? msg.timestamp,
    level: ((body.level as string) ?? (body.type as string) ?? "info").toLowerCase(),
    message: (body.message as string) ?? (body.content as string) ?? JSON.stringify(body),
  };
}

function formatTimestamp(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

export function LogsTab({ agents }: { agents: AgentSummary[] }) {
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [levelFilter, setLevelFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const seqRef = useRef(0);
  const logsEndRef = useRef<HTMLDivElement | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Reset when agent changes
  useEffect(() => {
    setLogs([]);
    seqRef.current = 0;
  }, [selectedAgent]);

  // Poll for logs
  useEffect(() => {
    if (!selectedAgent) return;

    const channels = [
      `agent.${selectedAgent}.outbox`,
      `agent.${selectedAgent}.inbox`,
    ];

    const poll = async () => {
      try {
        const newLogs: LogEntry[] = [];
        for (const channel of channels) {
          const msgs = await queryMessages(channel, {
            from_seq: seqRef.current,
            limit: 100,
          });
          for (const msg of msgs) {
            if (msg.sequence > seqRef.current) seqRef.current = msg.sequence;
            newLogs.push(parseLogEntry(msg));
          }
        }
        if (newLogs.length > 0) {
          setLogs((prev) => [...prev, ...newLogs]);
        }
      } catch {
        // Non-critical
      }
    };

    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [selectedAgent]);

  // Auto-scroll
  const scrollToBottom = useCallback(() => {
    if (autoScroll) {
      logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [autoScroll]);

  useEffect(() => {
    scrollToBottom();
  }, [logs, scrollToBottom]);

  const filteredLogs = logs.filter((entry) => {
    if (levelFilter !== "all" && entry.level !== levelFilter) return false;
    if (search && !entry.message.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="langley-logs-tab" data-testid="logs-tab">
      <div className="langley-logs-controls">
        <label htmlFor="logs-agent-select">Agent: </label>
        <select
          id="logs-agent-select"
          value={selectedAgent}
          onChange={(e) => setSelectedAgent(e.target.value)}
          data-testid="logs-agent-select"
        >
          <option value="">-- Select agent --</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.id.slice(0, 8)})
            </option>
          ))}
        </select>

        <label htmlFor="logs-level-filter">Level: </label>
        <select
          id="logs-level-filter"
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          data-testid="logs-level-filter"
        >
          <option value="all">All</option>
          <option value="info">Info</option>
          <option value="error">Error</option>
          <option value="message">Message</option>
          <option value="tool">Tool</option>
          <option value="delta">Delta</option>
        </select>

        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search logs..."
          className="langley-logs-search"
          data-testid="logs-search"
        />

        <label className="langley-logs-autoscroll">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
          />
          Auto-scroll
        </label>
      </div>
      <div className="langley-logs-stream" data-testid="logs-stream">
        {!selectedAgent ? (
          <div className="langley-empty">Select an agent to view logs.</div>
        ) : filteredLogs.length === 0 ? (
          <div className="langley-empty">No log entries yet.</div>
        ) : (
          filteredLogs.map((entry) => (
            <div
              key={entry.id}
              className={`langley-log-entry langley-log-${entry.level}`}
              data-testid={`log-${entry.id}`}
            >
              <span className="langley-log-time">{formatTimestamp(entry.timestamp)}</span>
              <span className="langley-log-level">{entry.level}</span>
              <span className="langley-log-message">{entry.message}</span>
            </div>
          ))
        )}
        <div ref={logsEndRef} />
      </div>
    </div>
  );
}
