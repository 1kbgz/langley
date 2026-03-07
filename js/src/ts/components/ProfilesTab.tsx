import { useState, useEffect, useCallback } from "react";
import {
  listProfiles,
  deleteProfile,
  createProfile,
  listPreconfiguredAgents,
  launchAgent,
} from "../api.ts";
import type { ProfileInfo, PreconfiguredAgent } from "../api.ts";

export function ProfilesTab() {
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const [preconfigured, setPreconfigured] = useState<PreconfiguredAgent[]>([]);
  const [selected, setSelected] = useState<ProfileInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [p, pc] = await Promise.all([
        listProfiles(),
        listPreconfiguredAgents().catch(() => [] as PreconfiguredAgent[]),
      ]);
      setProfiles(p);
      setPreconfigured(pc);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load profiles");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleDelete = async (id: string) => {
    try {
      await deleteProfile(id);
      if (selected?.id === id) setSelected(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete profile");
    }
  };

  const handleImport = async (agent: PreconfiguredAgent) => {
    try {
      await createProfile({
        name: agent.name,
        tenant_id: "default",
        command: [],
        llm_provider: agent.provider,
        model: agent.model,
        system_prompt: agent.system_prompt,
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import profile");
    }
  };

  const handleLaunch = async (profileId: string) => {
    try {
      await launchAgent(profileId);
      window.location.hash = "#/status";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to launch agent");
    }
  };

  return (
    <div className="langley-profiles-tab" data-testid="profiles-tab">
      {error && (
        <div className="langley-error">
          {error}
          <button className="langley-btn" onClick={() => setError(null)} style={{ marginLeft: 8 }}>
            Dismiss
          </button>
        </div>
      )}

      <div className="langley-profiles-layout">
        {/* Profile list */}
        <div className="langley-profiles-list">
          <h2>Saved Profiles</h2>
          {loading ? (
            <p className="langley-empty">Loading...</p>
          ) : profiles.length === 0 ? (
            <p className="langley-empty">No profiles saved.</p>
          ) : (
            <ul className="langley-profile-items">
              {profiles.map((p) => (
                <li
                  key={p.id}
                  className={`langley-profile-item${selected?.id === p.id ? " active" : ""}`}
                  data-testid={`profile-${p.id}`}
                >
                  <button
                    className="langley-profile-select"
                    onClick={() => setSelected(p)}
                  >
                    <span className="langley-profile-name">{p.name}</span>
                    <span className="langley-profile-meta">
                      v{p.version} · {p.llm_provider || "custom"}
                    </span>
                  </button>
                  <div className="langley-profile-actions">
                    <button
                      className="langley-btn langley-btn-primary"
                      onClick={() => handleLaunch(p.id)}
                      title="Launch agent with this profile"
                    >
                      ▶
                    </button>
                    <button
                      className="langley-btn langley-btn-danger"
                      onClick={() => handleDelete(p.id)}
                      data-testid={`delete-profile-${p.id}`}
                      title="Delete profile"
                    >
                      ×
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {/* Preconfigured agents */}
          {preconfigured.length > 0 && (
            <>
              <h2>Discovered Agents</h2>
              <ul className="langley-profile-items">
                {preconfigured.map((a) => (
                  <li
                    key={a.source}
                    className="langley-profile-item langley-profile-preconfigured"
                    data-testid={`preconfigured-${a.name}`}
                  >
                    <div className="langley-profile-select">
                      <span className="langley-profile-name">{a.name}</span>
                      <span className="langley-profile-meta">{a.provider}</span>
                    </div>
                    <div className="langley-profile-actions">
                      <button
                        className="langley-btn langley-btn-primary"
                        onClick={() => handleImport(a)}
                        title="Import as profile"
                      >
                        Import
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        {/* Profile detail */}
        <div className="langley-profile-detail">
          {selected ? (
            <div data-testid="profile-detail">
              <h2>{selected.name}</h2>
              <dl className="langley-profile-dl">
                <dt>ID</dt>
                <dd><code>{selected.id}</code></dd>
                <dt>Tenant</dt>
                <dd>{selected.tenant_id}</dd>
                <dt>Version</dt>
                <dd>{selected.version}</dd>
                <dt>Provider</dt>
                <dd>{selected.llm_provider || "—"}</dd>
                <dt>Model</dt>
                <dd>{selected.model || "—"}</dd>
                <dt>Command</dt>
                <dd>{selected.command.length > 0 ? selected.command.join(" ") : "—"}</dd>
                <dt>System Prompt</dt>
                <dd className="langley-profile-prompt">
                  {selected.system_prompt || "—"}
                </dd>
                <dt>Tags</dt>
                <dd>{selected.tags?.length > 0 ? selected.tags.join(", ") : "—"}</dd>
              </dl>
              <div className="langley-actions" style={{ marginTop: 16 }}>
                <button
                  className="langley-btn langley-btn-primary"
                  onClick={() => handleLaunch(selected.id)}
                >
                  Launch Agent
                </button>
                <button
                  className="langley-btn langley-btn-danger"
                  onClick={() => handleDelete(selected.id)}
                >
                  Delete
                </button>
              </div>
            </div>
          ) : (
            <div className="langley-empty">Select a profile to view details.</div>
          )}
        </div>
      </div>
    </div>
  );
}
