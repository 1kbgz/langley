import { useState, useCallback } from "react";
import type { AgentSummary } from "./types.ts";
import { ChatPanel } from "./ChatPanel.tsx";
import type { LangleyWsClient } from "../ws.ts";

interface ChatSession {
  agentId: string;
  agentName: string;
}

export function ChatTab({
  agents,
  initialAgentId,
  wsClient,
}: {
  agents: AgentSummary[];
  initialAgentId?: string;
  wsClient?: LangleyWsClient | null;
}) {
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    if (initialAgentId) {
      const agent = agents.find((a) => a.id === initialAgentId);
      return [
        { agentId: initialAgentId, agentName: agent?.name ?? initialAgentId },
      ];
    }
    return [];
  });
  const [activeSessionIdx, setActiveSessionIdx] = useState(0);
  const [selectedAgent, setSelectedAgent] = useState<string>("");

  const runningAgents = agents.filter((a) => a.status === "running");

  const openSession = useCallback(
    (agentId: string) => {
      const existing = sessions.findIndex((s) => s.agentId === agentId);
      if (existing >= 0) {
        setActiveSessionIdx(existing);
        return;
      }
      const agent = agents.find((a) => a.id === agentId);
      const newSession = { agentId, agentName: agent?.name ?? agentId };
      setSessions((prev) => [...prev, newSession]);
      setActiveSessionIdx(sessions.length);
      setSelectedAgent("");
    },
    [sessions, agents],
  );

  const closeSession = useCallback((idx: number) => {
    setSessions((prev) => prev.filter((_, i) => i !== idx));
    setActiveSessionIdx((prev) => {
      if (idx < prev) return prev - 1;
      if (idx === prev) return Math.max(0, prev - 1);
      return prev;
    });
  }, []);

  const activeSession = sessions[activeSessionIdx] ?? null;

  return (
    <div className="langley-chat-tab" data-testid="chat-tab">
      <div className="langley-chat-tab-header">
        <label htmlFor="chat-agent-select">Agent: </label>
        <select
          id="chat-agent-select"
          value={selectedAgent}
          onChange={(e) => setSelectedAgent(e.target.value)}
          data-testid="chat-agent-select"
        >
          <option value="">-- Select agent --</option>
          {runningAgents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.id.slice(0, 8)})
            </option>
          ))}
        </select>
        <button
          className="langley-btn langley-btn-primary"
          disabled={!selectedAgent}
          onClick={() => selectedAgent && openSession(selectedAgent)}
          data-testid="open-chat-session"
        >
          Open Chat
        </button>
      </div>

      {sessions.length > 0 && (
        <div className="langley-chat-sessions" data-testid="chat-sessions">
          {sessions.map((s, idx) => (
            <div
              key={s.agentId}
              className={`langley-chat-session-tab${idx === activeSessionIdx ? " active" : ""}`}
              data-testid={`chat-session-${s.agentId}`}
            >
              <button
                className="langley-chat-session-label"
                onClick={() => setActiveSessionIdx(idx)}
              >
                {s.agentName}
              </button>
              <button
                className="langley-chat-session-close"
                onClick={() => closeSession(idx)}
                title="Close session"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="langley-chat-tab-body">
        {activeSession ? (
          <ChatPanel
            agentId={activeSession.agentId}
            agentName={activeSession.agentName}
            wsClient={wsClient}
          />
        ) : (
          <div className="langley-empty" data-testid="no-chat-agent">
            {runningAgents.length === 0
              ? "No running agents. Launch an agent from the Status tab first."
              : "Select an agent and click Open Chat to start a session."}
          </div>
        )}
      </div>
    </div>
  );
}
