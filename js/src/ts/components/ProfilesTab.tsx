import { useState, useEffect, useCallback } from "react";
import {
  listProfiles,
  deleteProfile,
  createProfile,
  updateProfile,
  listPreconfiguredAgents,
  launchAgent,
  saveAgentToDisk,
  generateAgentProfile,
  listAgents,
} from "../api.ts";
import type { ProfileInfo, PreconfiguredAgent, AgentInfo } from "../api.ts";

export function ProfilesTab() {
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const [preconfigured, setPreconfigured] = useState<PreconfiguredAgent[]>([]);
  const [selected, setSelected] = useState<ProfileInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [runningAgents, setRunningAgents] = useState<AgentInfo[]>([]);
  const [saveFeedback, setSaveFeedback] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [rawEditing, setRawEditing] = useState(false);
  const [rawContent, setRawContent] = useState("");
  const [editFields, setEditFields] = useState<{
    name: string;
    llm_provider: string;
    model: string;
    system_prompt: string;
  }>({ name: "", llm_provider: "", model: "", system_prompt: "" });

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [p, pc, agents] = await Promise.all([
        listProfiles(),
        listPreconfiguredAgents().catch(() => [] as PreconfiguredAgent[]),
        listAgents(undefined, "running").catch(() => [] as AgentInfo[]),
      ]);
      setProfiles(p);
      setPreconfigured(pc);
      setRunningAgents(agents);
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

  const handleSaveToAgentsDir = async (profile: ProfileInfo) => {
    try {
      const result = await saveAgentToDisk({
        name: profile.name,
        provider: profile.llm_provider,
        model: profile.model,
        system_prompt: profile.system_prompt,
      });
      setSaveFeedback(`Saved to ${result.path}`);
      setTimeout(() => setSaveFeedback(null), 4000);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to save to agents dir",
      );
    }
  };

  const handleSaveToDisk = async (profile: ProfileInfo) => {
    const path = prompt(
      "Enter file path to save to:",
      `~/.langley/agents/${profile.name}.md`,
    );
    if (!path) return;
    try {
      const result = await saveAgentToDisk({
        name: profile.name,
        provider: profile.llm_provider,
        model: profile.model,
        system_prompt: profile.system_prompt,
        path,
      });
      setSaveFeedback(`Saved to ${result.path}`);
      setTimeout(() => setSaveFeedback(null), 4000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save to disk");
    }
  };

  const handleGenerateProfile = async (agentId: string) => {
    try {
      await generateAgentProfile(agentId);
      setSaveFeedback(
        "Profile generation prompt sent — check the agent's chat for results.",
      );
      setTimeout(() => setSaveFeedback(null), 5000);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to send profile generation prompt",
      );
    }
  };

  const startEditing = (profile: ProfileInfo) => {
    setEditing(true);
    setRawEditing(false);
    setEditFields({
      name: profile.name,
      llm_provider: profile.llm_provider,
      model: profile.model,
      system_prompt: profile.system_prompt,
    });
  };

  const startRawEditing = (profile: ProfileInfo) => {
    setRawEditing(true);
    setEditing(false);
    setRawContent(
      JSON.stringify(
        {
          name: profile.name,
          llm_provider: profile.llm_provider,
          model: profile.model,
          system_prompt: profile.system_prompt,
          command: profile.command,
          environment: profile.environment,
          tags: profile.tags,
        },
        null,
        2,
      ),
    );
  };

  const cancelEditing = () => {
    setEditing(false);
    setRawEditing(false);
  };

  const handleSaveRaw = async () => {
    if (!selected) return;
    try {
      const parsed = JSON.parse(rawContent);
      const updated = await updateProfile(selected.id, parsed);
      setSelected(updated);
      setRawEditing(false);
      await refresh();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Invalid JSON or failed to update",
      );
    }
  };

  const handleSaveEdit = async () => {
    if (!selected) return;
    try {
      const updated = await updateProfile(selected.id, editFields);
      setSelected(updated);
      setEditing(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update profile");
    }
  };

  return (
    <div className="langley-profiles-tab" data-testid="profiles-tab">
      {error && (
        <div className="langley-error">
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
      {saveFeedback && (
        <div className="langley-save-feedback" data-testid="save-feedback">
          {saveFeedback}
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
              {editing ? (
                <div
                  className="langley-profile-edit"
                  data-testid="profile-edit-form"
                >
                  <label>
                    Name
                    <input
                      type="text"
                      value={editFields.name}
                      onChange={(e) =>
                        setEditFields({ ...editFields, name: e.target.value })
                      }
                      data-testid="edit-name"
                    />
                  </label>
                  <label>
                    Provider
                    <input
                      type="text"
                      value={editFields.llm_provider}
                      onChange={(e) =>
                        setEditFields({
                          ...editFields,
                          llm_provider: e.target.value,
                        })
                      }
                      data-testid="edit-provider"
                    />
                  </label>
                  <label>
                    Model
                    <input
                      type="text"
                      value={editFields.model}
                      onChange={(e) =>
                        setEditFields({ ...editFields, model: e.target.value })
                      }
                      data-testid="edit-model"
                    />
                  </label>
                  <label>
                    System Prompt
                    <textarea
                      value={editFields.system_prompt}
                      onChange={(e) =>
                        setEditFields({
                          ...editFields,
                          system_prompt: e.target.value,
                        })
                      }
                      rows={6}
                      data-testid="edit-system-prompt"
                    />
                  </label>
                  <div className="langley-actions" style={{ marginTop: 12 }}>
                    <button
                      className="langley-btn langley-btn-primary"
                      onClick={handleSaveEdit}
                      data-testid="save-edit"
                    >
                      Save
                    </button>
                    <button className="langley-btn" onClick={cancelEditing}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : rawEditing ? (
                <div
                  className="langley-profile-edit"
                  data-testid="profile-raw-editor"
                >
                  <label>
                    Raw JSON
                    <textarea
                      value={rawContent}
                      onChange={(e) => setRawContent(e.target.value)}
                      rows={16}
                      className="langley-raw-editor"
                      data-testid="raw-editor"
                    />
                  </label>
                  <div className="langley-actions" style={{ marginTop: 12 }}>
                    <button
                      className="langley-btn langley-btn-primary"
                      onClick={handleSaveRaw}
                      data-testid="save-raw"
                    >
                      Save
                    </button>
                    <button className="langley-btn" onClick={cancelEditing}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <dl className="langley-profile-dl">
                    <dt>ID</dt>
                    <dd>
                      <code>{selected.id}</code>
                    </dd>
                    <dt>Tenant</dt>
                    <dd>{selected.tenant_id}</dd>
                    <dt>Version</dt>
                    <dd>{selected.version}</dd>
                    <dt>Provider</dt>
                    <dd>{selected.llm_provider || "—"}</dd>
                    <dt>Model</dt>
                    <dd>{selected.model || "—"}</dd>
                    <dt>Command</dt>
                    <dd>
                      {selected.command.length > 0
                        ? selected.command.join(" ")
                        : "—"}
                    </dd>
                    <dt>System Prompt</dt>
                    <dd className="langley-profile-prompt">
                      {selected.system_prompt || "—"}
                    </dd>
                    <dt>Tags</dt>
                    <dd>
                      {selected.tags?.length > 0
                        ? selected.tags.join(", ")
                        : "—"}
                    </dd>
                  </dl>
                  <div className="langley-actions" style={{ marginTop: 16 }}>
                    <button
                      className="langley-btn langley-btn-primary"
                      onClick={() => handleLaunch(selected.id)}
                    >
                      Launch Agent
                    </button>
                    <button
                      className="langley-btn"
                      onClick={() => startEditing(selected)}
                      data-testid="edit-profile"
                    >
                      Edit
                    </button>
                    <button
                      className="langley-btn"
                      onClick={() => startRawEditing(selected)}
                      data-testid="raw-edit-profile"
                    >
                      Raw JSON
                    </button>
                    <button
                      className="langley-btn"
                      onClick={() => handleSaveToAgentsDir(selected)}
                      title="Save to provider's agents directory"
                      data-testid="save-to-agents-dir"
                    >
                      Save to Agents Dir
                    </button>
                    <button
                      className="langley-btn"
                      onClick={() => handleSaveToDisk(selected)}
                      title="Save to a custom file path"
                      data-testid="save-to-disk"
                    >
                      Save to Disk
                    </button>
                    <button
                      className="langley-btn langley-btn-danger"
                      onClick={() => handleDelete(selected.id)}
                    >
                      Delete
                    </button>
                  </div>
                </>
              )}

              {/* Generate profile from a running agent */}
              {runningAgents.length > 0 && (
                <div
                  className="langley-generate-profile"
                  style={{ marginTop: 16 }}
                >
                  <h3>Generate Agent Self-Profile</h3>
                  <p className="langley-profile-meta">
                    Send a running agent a prompt to generate an agentic profile
                    of itself.
                  </p>
                  <div className="langley-actions">
                    {runningAgents.map((a) => (
                      <button
                        key={a.agent_id}
                        className="langley-btn"
                        onClick={() => handleGenerateProfile(a.agent_id)}
                        data-testid={`generate-profile-${a.agent_id}`}
                      >
                        Generate from {a.profile_name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="langley-empty">
              Select a profile to view details.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
