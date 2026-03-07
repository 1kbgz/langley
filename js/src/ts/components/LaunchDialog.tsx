import { useState } from "react";
import { createProfile, listPreconfiguredAgents } from "../api.ts";
import type { ProfileInfo, PreconfiguredAgent } from "../api.ts";
import { useEffect } from "react";

const PROVIDERS = [
  { value: "", label: "-- Select provider --" },
  { value: "github-copilot", label: "GitHub Copilot" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "custom", label: "Custom Command" },
];

const MODEL_SUGGESTIONS: Record<string, string[]> = {
  "github-copilot": [
    "claude-sonnet-4", "claude-opus-4", "gpt-4o", "gpt-4.1", "o4-mini", "o3-mini",
    "gemini-2.5-pro", "gemini-2.0-flash",
  ],
  openai: ["gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "o3-mini", "o4-mini"],
  anthropic: ["claude-sonnet-4", "claude-opus-4", "claude-haiku-3.5"],
  google: ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
};

export function LaunchDialog({
  profiles,
  onLaunch,
  onClose,
}: {
  profiles: ProfileInfo[];
  onLaunch: (profileId: string) => void;
  onClose: () => void;
}) {
  const [selectedProfile, setSelectedProfile] = useState("");
  const [preconfigured, setPreconfigured] = useState<PreconfiguredAgent[]>([]);

  // New profile form state
  const [showNewProfile, setShowNewProfile] = useState(false);
  const [newName, setNewName] = useState("");
  const [newTenant, setNewTenant] = useState("default");
  const [newProvider, setNewProvider] = useState("");
  const [newModel, setNewModel] = useState("");
  const [newSystemPrompt, setNewSystemPrompt] = useState("");
  const [newCommand, setNewCommand] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const models = MODEL_SUGGESTIONS[newProvider] ?? [];
  const isLLMProvider = newProvider && newProvider !== "custom";

  useEffect(() => {
    listPreconfiguredAgents().then(setPreconfigured).catch(() => {});
  }, []);

  const fillFromPreconfigured = (agent: PreconfiguredAgent) => {
    setShowNewProfile(true);
    setNewName(agent.name);
    setNewProvider(agent.provider);
    setNewModel(agent.model);
    setNewSystemPrompt(agent.system_prompt);
  };

  const handleCreateProfile = async () => {
    if (!newName) return;
    if (!isLLMProvider && !newCommand) return;
    setCreating(true);
    setCreateError(null);
    try {
      const parts = newCommand ? newCommand.split(/\s+/).filter(Boolean) : [];
      const profile = await createProfile({
        name: newName,
        tenant_id: newTenant,
        command: parts,
        llm_provider: newProvider === "custom" ? "" : newProvider,
        model: newModel,
        system_prompt: newSystemPrompt,
      });
      onLaunch(profile.id);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create profile");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="langley-dialog-overlay" data-testid="launch-dialog">
      <div className="langley-dialog">
        <div className="langley-dialog-header">
          <h2>Launch Agent</h2>
          <button className="langley-btn" onClick={onClose} data-testid="close-dialog">
            &times;
          </button>
        </div>

        {/* Preconfigured agents */}
        {preconfigured.length > 0 && !showNewProfile && (
          <div className="langley-dialog-section">
            <label>Preconfigured agents:</label>
            <div className="langley-preconfigured-list">
              {preconfigured.map((a) => (
                <button
                  key={a.source}
                  className="langley-preconfigured-item"
                  onClick={() => fillFromPreconfigured(a)}
                  data-testid={`preconfigured-${a.name}`}
                >
                  <span className="langley-preconfigured-name">{a.name}</span>
                  <span className="langley-preconfigured-provider">{a.provider}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {profiles.length > 0 && !showNewProfile && (
          <div className="langley-dialog-section">
            <label htmlFor="profile-select">Select a profile:</label>
            <select
              id="profile-select"
              value={selectedProfile}
              onChange={(e) => setSelectedProfile(e.target.value)}
              data-testid="profile-select"
            >
              <option value="">-- Choose --</option>
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} (v{p.version})
                </option>
              ))}
            </select>
            <button
              className="langley-btn langley-btn-primary"
              disabled={!selectedProfile}
              onClick={() => onLaunch(selectedProfile)}
              data-testid="launch-btn"
            >
              Launch
            </button>
          </div>
        )}

        <div className="langley-dialog-section">
          {!showNewProfile ? (
            <button
              className="langley-btn"
              onClick={() => setShowNewProfile(true)}
              data-testid="new-profile-toggle"
            >
              + New Profile
            </button>
          ) : (
            <div className="langley-new-profile" data-testid="new-profile-form">
              <h3>New Profile</h3>

              <label htmlFor="np-name">Name</label>
              <input
                id="np-name"
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="my-agent"
                data-testid="np-name"
              />

              <label htmlFor="np-tenant">Tenant ID</label>
              <input
                id="np-tenant"
                type="text"
                value={newTenant}
                onChange={(e) => setNewTenant(e.target.value)}
                data-testid="np-tenant"
              />

              <label htmlFor="np-provider">Provider</label>
              <select
                id="np-provider"
                value={newProvider}
                onChange={(e) => {
                  setNewProvider(e.target.value);
                  setNewModel("");
                }}
                data-testid="np-provider"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>

              {newProvider && newProvider !== "custom" && (
                <>
                  <label htmlFor="np-model">Model</label>
                  <input
                    id="np-model"
                    type="text"
                    list="np-model-suggestions"
                    value={newModel}
                    onChange={(e) => setNewModel(e.target.value)}
                    placeholder="Type or select a model…"
                    data-testid="np-model"
                    autoComplete="off"
                  />
                  {models.length > 0 && (
                    <datalist id="np-model-suggestions">
                      {models.map((m) => (
                        <option key={m} value={m} />
                      ))}
                    </datalist>
                  )}
                </>
              )}

              {(!newProvider || newProvider === "custom") && (
                <>
                  <label htmlFor="np-command">Command</label>
                  <input
                    id="np-command"
                    type="text"
                    value={newCommand}
                    onChange={(e) => setNewCommand(e.target.value)}
                    placeholder="python agent.py"
                    data-testid="np-command"
                  />
                </>
              )}

              <label htmlFor="np-prompt">Instructions</label>
              <textarea
                id="np-prompt"
                value={newSystemPrompt}
                onChange={(e) => setNewSystemPrompt(e.target.value)}
                placeholder="Describe what this agent should do..."
                rows={4}
                data-testid="np-prompt"
              />

              {createError && <div className="langley-error">{createError}</div>}
              <div className="langley-actions">
                <button
                  className="langley-btn langley-btn-primary"
                  onClick={handleCreateProfile}
                  disabled={creating || !newName || (!isLLMProvider && !newCommand)}
                  data-testid="create-and-launch"
                >
                  {creating ? "Creating..." : "Create & Launch"}
                </button>
                <button className="langley-btn" onClick={() => setShowNewProfile(false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
