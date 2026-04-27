import { useState, useEffect, useCallback, useRef } from "react";
import {
  getAgent,
  getProfile,
  queryMessages,
  queryAudit,
  sendMessageToAgent,
  stopAgent,
  killAgent,
  restartAgent,
  listCheckpoints,
} from "../api.ts";
import type {
  AgentInfo,
  ProfileInfo,
  AuditEntryInfo,
  CheckpointInfo,
} from "../api.ts";
import { StatusBadge } from "./StatusBadge.tsx";

type InspectorTab =
  | "chat"
  | "logs"
  | "messages"
  | "checkpoints"
  | "profile"
  | "approvals";

// Hard cap on in-memory entry buffers.  An LM-Studio-backed agent emits one
// outbox message per token, so without this cap the React arrays (and
// every render of them) grow without bound and the tab eventually crashes.
const MAX_ENTRIES = 500;
function capArray<T>(arr: T[]): T[] {
  return arr.length > MAX_ENTRIES ? arr.slice(arr.length - MAX_ENTRIES) : arr;
}
// Outbox event types that are streaming token chunks rather than
// human-meaningful entries; collapsed out of logs / messages views.
const NOISY_TYPES = new Set(["delta", "thinking", "turn_complete"]);

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  type?: string;
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

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString();
}

function formatDateTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600)
    return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export function AgentInspector({
  agentId,
  onBack,
  onAction,
}: {
  agentId: string;
  onBack: () => void;
  onAction?: (agentId: string, action: "stop" | "kill" | "restart") => void;
}) {
  const [agent, setAgent] = useState<AgentInfo | null>(null);
  const [profile, setProfile] = useState<ProfileInfo | null>(null);
  const [activeTab, setActiveTab] = useState<InspectorTab>("chat");
  const [error, setError] = useState<string | null>(null);

  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const outboxSeqRef = useRef(0);
  const inboxSeqRef = useRef(0);
  const pendingContentRef = useRef("");
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  // Logs state
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const logSeqRef = useRef(0);

  // Messages state
  const [messageEntries, setMessageEntries] = useState<MessageEntry[]>([]);
  const msgInSeqRef = useRef(0);
  const msgOutSeqRef = useRef(0);

  // Checkpoints state
  const [checkpoints, setCheckpoints] = useState<CheckpointInfo[]>([]);

  // Approvals state
  const [approvals, setApprovals] = useState<AuditEntryInfo[]>([]);

  // Fetch agent info
  useEffect(() => {
    const fetchAgent = async () => {
      try {
        const info = await getAgent(agentId);
        setAgent(info);
        if (info.profile_id) {
          try {
            const p = await getProfile(info.profile_id);
            setProfile(p);
          } catch {
            /* profile may not exist */
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch agent");
      }
    };
    fetchAgent();
    const interval = setInterval(fetchAgent, 5000);
    return () => clearInterval(interval);
  }, [agentId]);

  // Poll chat messages
  useEffect(() => {
    if (activeTab !== "chat") return;
    const poll = async () => {
      try {
        const outboxMsgs = await queryMessages(`agent.${agentId}.outbox`, {
          from_seq: outboxSeqRef.current,
          limit: 50,
        });
        const newMsgs: ChatMessage[] = [];
        for (const msg of outboxMsgs) {
          const body = msg.body as Record<string, unknown>;
          if (msg.sequence > outboxSeqRef.current)
            outboxSeqRef.current = msg.sequence;
          const type = (body.type as string) ?? "";
          if (type === "delta") {
            pendingContentRef.current += (body.content as string) ?? "";
          } else if (type === "message" || type === "turn_complete") {
            const content =
              pendingContentRef.current || (body.content as string) || "";
            pendingContentRef.current = "";
            if (content) {
              newMsgs.push({
                id: msg.id,
                role: "assistant",
                content,
                timestamp: msg.timestamp,
                type: "message",
              });
            }
          } else if (type === "tool_start") {
            newMsgs.push({
              id: msg.id,
              role: "system",
              content: `Using tool: ${body.tool_name}`,
              timestamp: msg.timestamp,
              type: "tool",
            });
          } else if (type === "error") {
            newMsgs.push({
              id: msg.id,
              role: "system",
              content: `Error: ${body.message}`,
              timestamp: msg.timestamp,
              type: "error",
            });
          }
        }
        if (newMsgs.length > 0)
          setChatMessages((prev) => capArray([...prev, ...newMsgs]));

        const inboxMsgs = await queryMessages(`agent.${agentId}.inbox`, {
          from_seq: inboxSeqRef.current,
          limit: 50,
        });
        for (const msg of inboxMsgs) {
          if (msg.sequence > inboxSeqRef.current)
            inboxSeqRef.current = msg.sequence;
        }
      } catch {
        /* non-critical */
      }
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [agentId, activeTab]);

  // Poll logs
  useEffect(() => {
    if (activeTab !== "logs") return;
    const poll = async () => {
      try {
        const newLogs: LogEntry[] = [];
        for (const ch of [
          `agent.${agentId}.outbox`,
          `agent.${agentId}.inbox`,
        ]) {
          const msgs = await queryMessages(ch, {
            from_seq: logSeqRef.current,
            limit: 100,
          });
          for (const msg of msgs) {
            if (msg.sequence > logSeqRef.current)
              logSeqRef.current = msg.sequence;
            const body = msg.body as Record<string, unknown>;
            const type = (body.type as string) ?? "";
            if (NOISY_TYPES.has(type)) continue;
            newLogs.push({
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
            });
          }
        }
        if (newLogs.length > 0)
          setLogs((prev) => capArray([...prev, ...newLogs]));
      } catch {
        /* non-critical */
      }
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [agentId, activeTab]);

  // Poll messages
  useEffect(() => {
    if (activeTab !== "messages") return;
    const poll = async () => {
      try {
        const entries: MessageEntry[] = [];
        const inboxMsgs = await queryMessages(`agent.${agentId}.inbox`, {
          from_seq: msgInSeqRef.current,
          limit: 100,
        });
        for (const msg of inboxMsgs) {
          if (msg.sequence > msgInSeqRef.current)
            msgInSeqRef.current = msg.sequence;
          const body = msg.body as Record<string, unknown>;
          const type = (body.type as string) ?? "";
          if (NOISY_TYPES.has(type)) continue;
          entries.push({
            id: msg.id,
            timestamp: msg.timestamp,
            channel: msg.channel,
            direction: "in",
            body:
              (body.text as string) ??
              (body.content as string) ??
              JSON.stringify(body),
          });
        }
        const outboxMsgs = await queryMessages(`agent.${agentId}.outbox`, {
          from_seq: msgOutSeqRef.current,
          limit: 100,
        });
        for (const msg of outboxMsgs) {
          if (msg.sequence > msgOutSeqRef.current)
            msgOutSeqRef.current = msg.sequence;
          const body = msg.body as Record<string, unknown>;
          const type = (body.type as string) ?? "";
          if (NOISY_TYPES.has(type)) continue;
          entries.push({
            id: msg.id,
            timestamp: msg.timestamp,
            channel: msg.channel,
            direction: "out",
            body:
              (body.text as string) ??
              (body.content as string) ??
              JSON.stringify(body),
          });
        }
        if (entries.length > 0) {
          entries.sort((a, b) => a.timestamp - b.timestamp);
          setMessageEntries((prev) => capArray([...prev, ...entries]));
        }
      } catch {
        /* non-critical */
      }
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [agentId, activeTab]);

  // Fetch checkpoints
  useEffect(() => {
    if (activeTab !== "checkpoints") return;
    const fetch = async () => {
      try {
        const cps = await listCheckpoints(agentId);
        setCheckpoints(cps);
      } catch {
        /* non-critical */
      }
    };
    fetch();
    const interval = setInterval(fetch, 10000);
    return () => clearInterval(interval);
  }, [agentId, activeTab]);

  // Fetch approvals (audit events of type approval_requested)
  useEffect(() => {
    if (activeTab !== "approvals") return;
    const fetch = async () => {
      try {
        const entries = await queryAudit("default", {
          agent_id: agentId,
          event_type: "approval_requested",
          limit: 100,
        });
        setApprovals(entries);
      } catch {
        /* non-critical */
      }
    };
    fetch();
    const interval = setInterval(fetch, 5000);
    return () => clearInterval(interval);
  }, [agentId, activeTab]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "auto" });
  }, [chatMessages]);

  const handleSendChat = useCallback(async () => {
    const text = chatInput.trim();
    if (!text || sending) return;
    setSending(true);
    setChatInput("");
    setChatMessages((prev) => [
      ...prev,
      {
        id: `user-${Date.now()}`,
        role: "user",
        content: text,
        timestamp: Date.now() / 1000,
      },
    ]);
    try {
      await sendMessageToAgent(agentId, { text });
    } catch {
      setChatMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "system",
          content: "Failed to send message",
          timestamp: Date.now() / 1000,
          type: "error",
        },
      ]);
    } finally {
      setSending(false);
    }
  }, [agentId, chatInput, sending]);

  const handleAction = useCallback(
    async (action: "stop" | "kill" | "restart") => {
      try {
        if (action === "stop") await stopAgent(agentId);
        else if (action === "kill") await killAgent(agentId);
        else if (action === "restart") await restartAgent(agentId);
        onAction?.(agentId, action);
      } catch (err) {
        setError(err instanceof Error ? err.message : `Failed to ${action}`);
      }
    },
    [agentId, onAction],
  );

  const tabs: { id: InspectorTab; label: string }[] = [
    { id: "chat", label: "Chat" },
    { id: "logs", label: "Logs" },
    { id: "messages", label: "Messages" },
    { id: "checkpoints", label: "Checkpoints" },
    { id: "profile", label: "Profile" },
    { id: "approvals", label: "Approvals" },
  ];

  return (
    <div className="langley-inspector" data-testid="agent-inspector">
      {/* Header */}
      <div className="langley-inspector-header">
        <button
          className="langley-btn"
          onClick={onBack}
          data-testid="inspector-back"
        >
          ← Back
        </button>
        <h2>{agent?.profile_name ?? agentId}</h2>
        {agent && (
          <StatusBadge
            status={
              agent.status as "running" | "stopped" | "errored" | "pending"
            }
          />
        )}
        {agent?.status === "running" && (
          <div className="langley-actions">
            <button
              className="langley-btn"
              onClick={() => handleAction("stop")}
            >
              Stop
            </button>
            <button
              className="langley-btn langley-btn-danger"
              onClick={() => handleAction("kill")}
            >
              Kill
            </button>
            <button
              className="langley-btn"
              onClick={() => handleAction("restart")}
            >
              Restart
            </button>
          </div>
        )}
        {agent &&
          (agent.status === "stopped" || agent.status === "errored") && (
            <div className="langley-actions">
              <button
                className="langley-btn langley-btn-primary"
                data-testid="inspector-restart"
                onClick={() => handleAction("restart")}
              >
                Restart
              </button>
            </div>
          )}
      </div>

      {error && (
        <div className="langley-error">
          {error}
          <button
            className="langley-btn"
            onClick={() => setError(null)}
            style={{ marginLeft: 8 }}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Status Panel */}
      {agent && (
        <div
          className="langley-inspector-status"
          data-testid="inspector-status"
        >
          <div className="langley-inspector-stat">
            <span className="langley-inspector-stat-label">Status</span>
            <span className="langley-inspector-stat-value">{agent.status}</span>
          </div>
          <div className="langley-inspector-stat">
            <span className="langley-inspector-stat-label">Uptime</span>
            <span className="langley-inspector-stat-value">
              {formatUptime(agent.uptime_seconds)}
            </span>
          </div>
          <div className="langley-inspector-stat">
            <span className="langley-inspector-stat-label">PID</span>
            <span className="langley-inspector-stat-value">
              {agent.pid ?? "—"}
            </span>
          </div>
          <div className="langley-inspector-stat">
            <span className="langley-inspector-stat-label">Restarts</span>
            <span className="langley-inspector-stat-value">
              {agent.restart_count}
            </span>
          </div>
          <div className="langley-inspector-stat">
            <span className="langley-inspector-stat-label">Restart Policy</span>
            <span className="langley-inspector-stat-value">
              {agent.restart_policy}
            </span>
          </div>
          <div className="langley-inspector-stat">
            <span className="langley-inspector-stat-label">Last Heartbeat</span>
            <span className="langley-inspector-stat-value">
              {agent.last_heartbeat ? formatTime(agent.last_heartbeat) : "—"}
            </span>
          </div>
          {agent.error_message && (
            <div className="langley-inspector-stat langley-inspector-stat-error">
              <span className="langley-inspector-stat-label">Error</span>
              <span className="langley-inspector-stat-value">
                {agent.error_message}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Tab bar */}
      <nav className="langley-inspector-tabs" data-testid="inspector-tabs">
        {tabs.map(({ id, label }) => (
          <button
            key={id}
            className={`langley-inspector-tab${activeTab === id ? " active" : ""}`}
            onClick={() => setActiveTab(id)}
            data-testid={`inspector-tab-${id}`}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* Tab content */}
      <div
        className="langley-inspector-content"
        data-testid="inspector-content"
      >
        {activeTab === "chat" && (
          <div className="langley-inspector-chat">
            <div className="langley-chat-messages">
              {chatMessages.length === 0 && (
                <div className="langley-empty">
                  No messages yet. Send a message to start chatting.
                </div>
              )}
              {chatMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`langley-chat-message langley-chat-${msg.role}`}
                >
                  <span className="langley-chat-role">{msg.role}</span>
                  <span className="langley-chat-content">{msg.content}</span>
                  <span className="langley-chat-time">
                    {formatTime(msg.timestamp)}
                  </span>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>
            <div className="langley-chat-input-bar">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSendChat()}
                placeholder="Send a message..."
                className="langley-chat-input"
                disabled={agent?.status !== "running"}
                data-testid="inspector-chat-input"
              />
              <button
                className="langley-btn langley-btn-primary"
                onClick={handleSendChat}
                disabled={
                  !chatInput.trim() || sending || agent?.status !== "running"
                }
                data-testid="inspector-chat-send"
              >
                Send
              </button>
            </div>
          </div>
        )}

        {activeTab === "logs" && (
          <div className="langley-inspector-logs">
            {logs.length === 0 ? (
              <div className="langley-empty">No log entries yet.</div>
            ) : (
              logs.map((entry) => (
                <div
                  key={entry.id}
                  className={`langley-log-entry langley-log-${entry.level}`}
                >
                  <span className="langley-log-time">
                    {formatTime(entry.timestamp)}
                  </span>
                  <span className="langley-log-level">{entry.level}</span>
                  <span className="langley-log-message">{entry.message}</span>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "messages" && (
          <div className="langley-inspector-messages">
            {messageEntries.length === 0 ? (
              <div className="langley-empty">No messages yet.</div>
            ) : (
              messageEntries.map((entry) => (
                <div
                  key={entry.id}
                  className={`langley-log-entry langley-msg-${entry.direction}`}
                >
                  <span className="langley-log-time">
                    {formatTime(entry.timestamp)}
                  </span>
                  <span className="langley-log-level">
                    {entry.direction === "in" ? "← IN" : "→ OUT"}
                  </span>
                  <span className="langley-log-message">{entry.body}</span>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "checkpoints" && (
          <div className="langley-inspector-checkpoints">
            {checkpoints.length === 0 ? (
              <div className="langley-empty">
                No checkpoints saved for this agent.
              </div>
            ) : (
              <table className="langley-agent-table">
                <thead>
                  <tr>
                    <th>Sequence</th>
                    <th>Timestamp</th>
                    <th>Machine</th>
                    <th>Metadata</th>
                  </tr>
                </thead>
                <tbody>
                  {checkpoints.map((cp) => (
                    <tr key={cp.id}>
                      <td>{cp.sequence}</td>
                      <td>{formatDateTime(cp.timestamp)}</td>
                      <td>{cp.machine_id || "—"}</td>
                      <td>
                        <code>{JSON.stringify(cp.metadata)}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {activeTab === "profile" && (
          <div className="langley-inspector-profile">
            {profile ? (
              <dl className="langley-profile-dl">
                <dt>Profile ID</dt>
                <dd>
                  <code>{profile.id}</code>
                </dd>
                <dt>Name</dt>
                <dd>{profile.name}</dd>
                <dt>Version</dt>
                <dd>{profile.version}</dd>
                <dt>Tenant</dt>
                <dd>{profile.tenant_id}</dd>
                <dt>Provider</dt>
                <dd>{profile.llm_provider || "—"}</dd>
                <dt>Model</dt>
                <dd>{profile.model || "—"}</dd>
                <dt>Command</dt>
                <dd>
                  {profile.command.length > 0 ? profile.command.join(" ") : "—"}
                </dd>
                <dt>System Prompt</dt>
                <dd className="langley-profile-prompt">
                  {profile.system_prompt || "—"}
                </dd>
                <dt>Tags</dt>
                <dd>
                  {profile.tags?.length > 0 ? profile.tags.join(", ") : "—"}
                </dd>
              </dl>
            ) : (
              <div className="langley-empty">Profile not available.</div>
            )}
          </div>
        )}

        {activeTab === "approvals" && (
          <div className="langley-inspector-approvals">
            {approvals.length === 0 ? (
              <div className="langley-empty">No approval requests.</div>
            ) : (
              approvals.map((entry) => (
                <div key={entry.id} className="langley-approval-entry">
                  <span className="langley-log-time">
                    {formatTime(entry.timestamp)}
                  </span>
                  <span className="langley-approval-desc">
                    {(entry.payload.description as string) ?? entry.event_type}
                  </span>
                  <span className="langley-approval-status">
                    {(entry.payload.status as string) ?? "pending"}
                  </span>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
