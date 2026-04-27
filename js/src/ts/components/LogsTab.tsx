import { useState, useEffect, useRef, useCallback } from "react";
import { queryMessages, queryAudit } from "../api.ts";
import type { AuditEntryInfo } from "../api.ts";
import type { AgentSummary } from "./types.ts";

type LogView = "logs" | "messages" | "audit";

// Hard cap on the in-memory entry buffer to keep React from choking when an
// agent streams thousands of token deltas on its outbox channel.  Without
// this, the array (and every render of the list) grows without bound and
// the tab eventually crashes.
const MAX_ENTRIES = 500;

// Outbox event types that represent streaming token chunks rather than
// human-meaningful log lines.  We collapse them out of the logs / messages
// views; the coalesced ``message`` entry covers the full assistant turn.
const NOISY_TYPES = new Set(["delta", "thinking", "turn_complete"]);

function isNoisy(body: unknown): boolean {
  if (!body || typeof body !== "object") return false;
  const type = (body as Record<string, unknown>).type;
  return typeof type === "string" && NOISY_TYPES.has(type);
}

interface LogEntry {
  id: string;
  timestamp: number;
  level: string;
  message: string;
}

interface MessageEntry {
  id: string;
  timestamp: number;
  channel: string;
  direction: "in" | "out";
  body: string;
}

function parseLogEntry(msg: {
  id: string;
  body: unknown;
  timestamp: number;
}): LogEntry {
  const body = msg.body as Record<string, unknown>;
  return {
    id: msg.id,
    timestamp: (body.timestamp as number) ?? msg.timestamp,
    level: (
      (body.level as string) ??
      (body.type as string) ??
      "info"
    ).toLowerCase(),
    message:
      (body.message as string) ??
      (body.content as string) ??
      JSON.stringify(body),
  };
}

function parseMessageEntry(
  msg: { id: string; body: unknown; timestamp: number; channel: string },
  agentId: string,
): MessageEntry {
  const body = msg.body as Record<string, unknown>;
  return {
    id: msg.id,
    timestamp: msg.timestamp,
    channel: msg.channel,
    direction: msg.channel.endsWith(".inbox") ? "in" : "out",
    body:
      (body.text as string) ??
      (body.content as string) ??
      (body.message as string) ??
      JSON.stringify(body),
  };
}

function formatTimestamp(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

export function LogsTab({ agents }: { agents: AgentSummary[] }) {
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [view, setView] = useState<LogView>("logs");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [messageEntries, setMessageEntries] = useState<MessageEntry[]>([]);
  const [auditEntries, setAuditEntries] = useState<AuditEntryInfo[]>([]);
  const [levelFilter, setLevelFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const seqRef = useRef(0);
  const msgSeqInRef = useRef(0);
  const msgSeqOutRef = useRef(0);
  const logsEndRef = useRef<HTMLDivElement | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Reset when agent or view changes
  useEffect(() => {
    setLogs([]);
    setMessageEntries([]);
    setAuditEntries([]);
    seqRef.current = 0;
    msgSeqInRef.current = 0;
    msgSeqOutRef.current = 0;
  }, [selectedAgent, view]);

  // Poll for logs
  useEffect(() => {
    if (!selectedAgent || view !== "logs") return;

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
            if (isNoisy(msg.body)) continue;
            newLogs.push(parseLogEntry(msg));
          }
        }
        if (newLogs.length > 0) {
          setLogs((prev) => {
            const merged = [...prev, ...newLogs];
            return merged.length > MAX_ENTRIES
              ? merged.slice(merged.length - MAX_ENTRIES)
              : merged;
          });
        }
      } catch {
        // Non-critical
      }
    };

    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [selectedAgent, view]);

  // Poll for messages view
  useEffect(() => {
    if (!selectedAgent || view !== "messages") return;

    const poll = async () => {
      try {
        const newEntries: MessageEntry[] = [];
        const inboxMsgs = await queryMessages(`agent.${selectedAgent}.inbox`, {
          from_seq: msgSeqInRef.current,
          limit: 100,
        });
        for (const msg of inboxMsgs) {
          if (msg.sequence > msgSeqInRef.current)
            msgSeqInRef.current = msg.sequence;
          if (isNoisy(msg.body)) continue;
          newEntries.push(parseMessageEntry(msg, selectedAgent));
        }
        const outboxMsgs = await queryMessages(
          `agent.${selectedAgent}.outbox`,
          {
            from_seq: msgSeqOutRef.current,
            limit: 100,
          },
        );
        for (const msg of outboxMsgs) {
          if (msg.sequence > msgSeqOutRef.current)
            msgSeqOutRef.current = msg.sequence;
          if (isNoisy(msg.body)) continue;
          newEntries.push(parseMessageEntry(msg, selectedAgent));
        }
        if (newEntries.length > 0) {
          newEntries.sort((a, b) => a.timestamp - b.timestamp);
          setMessageEntries((prev) => {
            const merged = [...prev, ...newEntries];
            return merged.length > MAX_ENTRIES
              ? merged.slice(merged.length - MAX_ENTRIES)
              : merged;
          });
        }
      } catch {
        // Non-critical
      }
    };

    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [selectedAgent, view]);

  // Poll for audit trail
  useEffect(() => {
    if (!selectedAgent || view !== "audit") return;

    const poll = async () => {
      try {
        const entries = await queryAudit("default", {
          agent_id: selectedAgent,
          limit: 200,
        });
        setAuditEntries(entries);
      } catch {
        // Non-critical
      }
    };

    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, [selectedAgent, view]);

  // Auto-scroll
  const scrollToBottom = useCallback(() => {
    if (autoScroll) {
      logsEndRef.current?.scrollIntoView({ behavior: "auto" });
    }
  }, [autoScroll]);

  useEffect(() => {
    scrollToBottom();
  }, [logs, messageEntries, auditEntries, scrollToBottom]);

  const filteredLogs = logs.filter((entry) => {
    if (levelFilter !== "all" && entry.level !== levelFilter) return false;
    if (search && !entry.message.toLowerCase().includes(search.toLowerCase()))
      return false;
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

        <label htmlFor="logs-view-select">View: </label>
        <select
          id="logs-view-select"
          value={view}
          onChange={(e) => setView(e.target.value as LogView)}
          data-testid="logs-view-select"
        >
          <option value="logs">Logs</option>
          <option value="messages">Messages</option>
          <option value="audit">Audit Trail</option>
        </select>

        {view === "logs" && (
          <>
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
          </>
        )}

        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search..."
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
          <div className="langley-empty">Select an agent to view {view}.</div>
        ) : view === "logs" ? (
          filteredLogs.length === 0 ? (
            <div className="langley-empty">No log entries yet.</div>
          ) : (
            filteredLogs.map((entry) => (
              <div
                key={entry.id}
                className={`langley-log-entry langley-log-${entry.level}`}
                data-testid={`log-${entry.id}`}
              >
                <span className="langley-log-time">
                  {formatTimestamp(entry.timestamp)}
                </span>
                <span className="langley-log-level">{entry.level}</span>
                <span className="langley-log-message">{entry.message}</span>
              </div>
            ))
          )
        ) : view === "messages" ? (
          messageEntries.length === 0 ? (
            <div className="langley-empty">No messages yet.</div>
          ) : (
            messageEntries
              .filter(
                (m) =>
                  !search ||
                  m.body.toLowerCase().includes(search.toLowerCase()),
              )
              .map((entry) => (
                <div
                  key={entry.id}
                  className={`langley-log-entry langley-msg-${entry.direction}`}
                  data-testid={`msg-${entry.id}`}
                >
                  <span className="langley-log-time">
                    {formatTimestamp(entry.timestamp)}
                  </span>
                  <span className="langley-log-level">
                    {entry.direction === "in" ? "← IN" : "→ OUT"}
                  </span>
                  <span className="langley-log-message">{entry.body}</span>
                </div>
              ))
          )
        ) : auditEntries.length === 0 ? (
          <div className="langley-empty">No audit entries yet.</div>
        ) : (
          auditEntries
            .filter(
              (a) =>
                !search ||
                a.event_type.toLowerCase().includes(search.toLowerCase()) ||
                JSON.stringify(a.payload)
                  .toLowerCase()
                  .includes(search.toLowerCase()),
            )
            .map((entry) => (
              <div
                key={entry.id}
                className="langley-log-entry langley-log-audit"
                data-testid={`audit-${entry.id}`}
              >
                <span className="langley-log-time">
                  {formatTimestamp(entry.timestamp)}
                </span>
                <span className="langley-log-level">{entry.event_type}</span>
                <span className="langley-log-message">
                  {JSON.stringify(entry.payload)}
                </span>
              </div>
            ))
        )}
        <div ref={logsEndRef} />
      </div>
    </div>
  );
}
