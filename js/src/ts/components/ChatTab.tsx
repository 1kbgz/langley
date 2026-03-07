import { useState } from "react";
import type { AgentSummary } from "./types.ts";
import { ChatPanel } from "./ChatPanel.tsx";

export function ChatTab({
  agents,
  initialAgentId,
}: {
  agents: AgentSummary[];
  initialAgentId?: string;
}) {
  const [selectedAgent, setSelectedAgent] = useState<string>(initialAgentId ?? "");

  const runningAgents = agents.filter((a) => a.status === "running");
  const agentName = agents.find((a) => a.id === selectedAgent)?.name ?? selectedAgent;

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
      </div>
      <div className="langley-chat-tab-body">
        {selectedAgent ? (
          <ChatPanel agentId={selectedAgent} agentName={agentName} />
        ) : (
          <div className="langley-empty" data-testid="no-chat-agent">
            {runningAgents.length === 0
              ? "No running agents. Launch an agent from the Status tab first."
              : "Select an agent to start chatting."}
          </div>
        )}
      </div>
    </div>
  );
}
