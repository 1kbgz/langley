import { useState, useCallback } from "react";
import type { AgentSummary } from "./types.ts";
import { StatusBadge } from "./StatusBadge.tsx";

export function AgentTable({
  agents,
  onAction,
  onChat,
  onInspect,
  onBulkAction,
}: {
  agents: AgentSummary[];
  onAction?: (agentId: string, action: "stop" | "kill" | "restart") => void;
  onChat?: (agentId: string) => void;
  onInspect?: (agentId: string) => void;
  onBulkAction?: (
    agentIds: string[],
    action: "stop" | "kill" | "restart",
  ) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelected((prev) =>
      prev.size === agents.length
        ? new Set()
        : new Set(agents.map((a) => a.id)),
    );
  }, [agents]);

  const handleBulk = useCallback(
    (action: "stop" | "kill" | "restart") => {
      if (selected.size === 0) return;
      onBulkAction?.([...selected], action);
      setSelected(new Set());
    },
    [selected, onBulkAction],
  );

  if (agents.length === 0) {
    return (
      <p className="langley-empty" data-testid="no-agents">
        No agents running.
      </p>
    );
  }
  return (
    <>
      {selected.size > 0 && onBulkAction && (
        <div className="langley-bulk-actions" data-testid="bulk-actions">
          <span>{selected.size} selected</span>
          <button className="langley-btn" onClick={() => handleBulk("stop")}>
            Stop
          </button>
          <button
            className="langley-btn langley-btn-danger"
            onClick={() => handleBulk("kill")}
          >
            Kill
          </button>
          <button className="langley-btn" onClick={() => handleBulk("restart")}>
            Restart
          </button>
        </div>
      )}
      <table className="langley-agent-table" data-testid="agent-table">
        <thead>
          <tr>
            {onBulkAction && (
              <th style={{ width: 32 }}>
                <input
                  type="checkbox"
                  checked={selected.size === agents.length}
                  onChange={toggleSelectAll}
                  data-testid="select-all"
                />
              </th>
            )}
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
              {onBulkAction && (
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(agent.id)}
                    onChange={() => toggleSelect(agent.id)}
                    data-testid={`select-${agent.id}`}
                  />
                </td>
              )}
              <td>
                <StatusBadge status={agent.status} />
              </td>
              <td>
                {onInspect ? (
                  <button
                    className="langley-agent-name-link"
                    onClick={() => onInspect(agent.id)}
                    data-testid={`inspect-${agent.id}`}
                  >
                    {agent.name}
                  </button>
                ) : (
                  agent.name
                )}
              </td>
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
                {(agent.status === "stopped" || agent.status === "errored") && (
                  <div className="langley-actions">
                    <button
                      className="langley-btn langley-btn-primary"
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
    </>
  );
}
