import type { AgentStatus } from "./types.ts";

const colors: Record<AgentStatus, string> = {
  running: "#22c55e",
  stopped: "#94a3b8",
  errored: "#ef4444",
  pending: "#f59e0b",
};

export function StatusBadge({ status }: { status: AgentStatus }) {
  return (
    <span
      className="langley-status-badge"
      style={{ backgroundColor: colors[status] }}
      data-testid={`status-${status}`}
    />
  );
}
