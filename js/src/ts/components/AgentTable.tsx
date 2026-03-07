import type { AgentSummary } from "./types.ts";
import { StatusBadge } from "./StatusBadge.tsx";

export function AgentTable({
  agents,
  onAction,
  onChat,
}: {
  agents: AgentSummary[];
  onAction?: (agentId: string, action: "stop" | "kill" | "restart") => void;
  onChat?: (agentId: string) => void;
}) {
  if (agents.length === 0) {
    return (
      <p className="langley-empty" data-testid="no-agents">
        No agents running.
      </p>
    );
  }
  return (
    <table className="langley-agent-table" data-testid="agent-table">
      <thead>
        <tr>
          <th>Status</th>
          <th>Name</th>
          <th>Profile</th>
          <th>Uptime</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {agents.map((agent) => (
          <tr key={agent.id} data-testid={`agent-row-${agent.id}`}>
            <td>
              <StatusBadge status={agent.status} />
            </td>
            <td>{agent.name}</td>
            <td>{agent.profile}</td>
            <td>{Math.floor(agent.uptime_seconds)}s</td>
            <td>
              {agent.status === "running" && (
                <div className="langley-actions">
                  <button
                    className="langley-btn langley-btn-primary"
                    data-testid={`chat-${agent.id}`}
                    onClick={() => onChat?.(agent.id)}
                  >
                    Chat
                  </button>
                  <button
                    className="langley-btn"
                    data-testid={`stop-${agent.id}`}
                    onClick={() => onAction?.(agent.id, "stop")}
                  >
                    Stop
                  </button>
                  <button
                    className="langley-btn langley-btn-danger"
                    data-testid={`kill-${agent.id}`}
                    onClick={() => onAction?.(agent.id, "kill")}
                  >
                    Kill
                  </button>
                  <button
                    className="langley-btn"
                    data-testid={`restart-${agent.id}`}
                    onClick={() => onAction?.(agent.id, "restart")}
                  >
                    Restart
                  </button>
                </div>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
