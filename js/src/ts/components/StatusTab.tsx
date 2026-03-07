import { useState, useCallback } from "react";
import type { AuditEntryInfo } from "../api.ts";
import {
  stopAgent,
  killAgent,
  restartAgent,
  launchAgent,
  listProfiles,
} from "../api.ts";
import type { ProfileInfo } from "../api.ts";
import type { AgentSummary, AgentStatus } from "./types.ts";
import { SummaryCards } from "./SummaryCards.tsx";
import { AgentTable } from "./AgentTable.tsx";
import { ActivityFeed } from "./ActivityFeed.tsx";
import { LaunchDialog } from "./LaunchDialog.tsx";

export function StatusTab({
  agents,
  activity,
  onAgentsChanged,
  onNavigateChat,
  onNavigateInspect,
  onBulkAction,
}: {
  agents: AgentSummary[];
  activity: AuditEntryInfo[];
  onAgentsChanged: () => void;
  onNavigateChat: (agentId: string) => void;
  onNavigateInspect?: (agentId: string) => void;
  onBulkAction?: (
    agentIds: string[],
    action: "stop" | "kill" | "restart",
  ) => void;
}) {
  const [filter, setFilter] = useState<AgentStatus | "all">("all");
  const [showLaunch, setShowLaunch] = useState(false);
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const [error, setError] = useState<string | null>(null);

  const handleAction = useCallback(
    async (agentId: string, action: "stop" | "kill" | "restart") => {
      try {
        if (action === "stop") await stopAgent(agentId);
        else if (action === "kill") await killAgent(agentId);
        else if (action === "restart") await restartAgent(agentId);
        onAgentsChanged();
      } catch (err) {
        setError(
          err instanceof Error ? err.message : `Failed to ${action} agent`,
        );
      }
    },
    [onAgentsChanged],
  );

  const handleLaunch = useCallback(
    async (profileId: string) => {
      try {
        await launchAgent(profileId);
        setShowLaunch(false);
        onAgentsChanged();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to launch agent");
      }
    },
    [onAgentsChanged],
  );

  const openLaunchDialog = useCallback(async () => {
    try {
      const p = await listProfiles();
      setProfiles(p);
    } catch {
      setProfiles([]);
    }
    setShowLaunch(true);
  }, []);

  const filteredAgents =
    filter === "all" ? agents : agents.filter((a) => a.status === filter);

  return (
    <>
      {error && (
        <div className="langley-error" data-testid="error-banner">
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
      <SummaryCards agents={agents} />
      <div className="langley-controls">
        <label htmlFor="status-filter">Filter by status: </label>
        <select
          id="status-filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value as AgentStatus | "all")}
          data-testid="status-filter"
        >
          <option value="all">All</option>
          <option value="running">Running</option>
          <option value="stopped">Stopped</option>
          <option value="errored">Errored</option>
          <option value="pending">Pending</option>
        </select>
        <button
          className="langley-btn langley-btn-primary"
          onClick={openLaunchDialog}
          data-testid="open-launch"
        >
          + Launch Agent
        </button>
      </div>
      <AgentTable
        agents={filteredAgents}
        onAction={handleAction}
        onChat={onNavigateChat}
        onInspect={onNavigateInspect}
        onBulkAction={onBulkAction}
      />
      <ActivityFeed events={activity} />
      {showLaunch && (
        <LaunchDialog
          profiles={profiles}
          onLaunch={handleLaunch}
          onClose={() => setShowLaunch(false)}
        />
      )}
    </>
  );
}
