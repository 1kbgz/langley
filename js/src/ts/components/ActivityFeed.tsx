import type { AuditEntryInfo } from "../api.ts";

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

export function ActivityFeed({ events }: { events: AuditEntryInfo[] }) {
  if (events.length === 0) {
    return (
      <p className="langley-empty" data-testid="no-activity">
        No recent activity.
      </p>
    );
  }
  return (
    <div className="langley-activity-feed" data-testid="activity-feed">
      <h2>Activity</h2>
      <ul className="langley-activity-list">
        {events.map((ev) => (
          <li key={ev.id} className="langley-activity-item" data-testid={`activity-${ev.id}`}>
            <span className="langley-activity-type">{ev.event_type}</span>
            <span className="langley-activity-agent">{ev.agent_id.slice(0, 8)}</span>
            <span className="langley-activity-time">{formatTime(ev.timestamp)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
