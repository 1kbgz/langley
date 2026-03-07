import type { AgentSummary } from "./types.ts";

export function SummaryCards({ agents }: { agents: AgentSummary[] }) {
  const counts = {
    total: agents.length,
    running: agents.filter((a) => a.status === "running").length,
    stopped: agents.filter((a) => a.status === "stopped").length,
    errored: agents.filter((a) => a.status === "errored").length,
    pending: agents.filter((a) => a.status === "pending").length,
  };
  return (
    <div className="langley-summary-cards" data-testid="summary-cards">
      <div className="langley-card" data-testid="card-total">
        <div className="langley-card-value">{counts.total}</div>
        <div className="langley-card-label">Total</div>
      </div>
      <div className="langley-card" data-testid="card-running">
        <div className="langley-card-value">{counts.running}</div>
        <div className="langley-card-label">Running</div>
      </div>
      <div className="langley-card" data-testid="card-stopped">
        <div className="langley-card-value">{counts.stopped}</div>
        <div className="langley-card-label">Stopped</div>
      </div>
      <div className="langley-card" data-testid="card-errored">
        <div className="langley-card-value">{counts.errored}</div>
        <div className="langley-card-label">Errored</div>
      </div>
      <div className="langley-card" data-testid="card-pending">
        <div className="langley-card-value">{counts.pending}</div>
        <div className="langley-card-label">Pending</div>
      </div>
    </div>
  );
}
