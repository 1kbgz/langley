export type AgentStatus = "running" | "stopped" | "errored" | "pending";

export interface AgentSummary {
  id: string;
  name: string;
  status: AgentStatus;
  profile: string;
  tenant_id: string;
  uptime_seconds: number;
}
