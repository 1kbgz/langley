import { useState, useEffect } from "react";
import {
  createProfile,
  listPreconfiguredAgents,
  fetchProviders,
} from "../api.ts";
import type {
  ProfileInfo,
  PreconfiguredAgent,
  ProviderInfo,
  ModelBilling,
} from "../api.ts";

function formatBilling(billing?: ModelBilling): string {
  if (!billing) return "";
  if (billing.type === "multiplier") {
    if (billing.multiplier === 0) return "Included";
    return `${billing.multiplier}× premium`;
  }
  if (billing.type === "per_token") {
    return `$${billing.input_per_mtok} / $${billing.output_per_mtok} per MTok`;
  }
  return "";
}

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
  const [providers, setProviders] = useState<ProviderInfo[]>([]);

  // New profile form state
  const [showNewProfile, setShowNewProfile] = useState(false);
  const [newName, setNewName] = useState("");
  const [newProvider, setNewProvider] = useState("");
  const [newModel, setNewModel] = useState("");
  const [newSystemPrompt, setNewSystemPrompt] = useState("");
  const [newCommand, setNewCommand] = useState("");
  const [newBaseUrl, setNewBaseUrl] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const providerOptions = [
    { value: "", label: "-- Select provider --" },
    ...providers.map((p) => ({ value: p.id, label: p.name })),
    { value: "custom", label: "Custom Command" },
  ];
  const selectedProviderInfo = providers.find((p) => p.id === newProvider);
  const providerModels = selectedProviderInfo?.models ?? [];
  const currentModelBilling = providerModels.find(
    (m) => m.id === newModel,
  )?.billing;
  const isLLMProvider = newProvider && newProvider !== "custom";
  // Providers like LM Studio expose a base_url; auto-fill it when picked.
  const providerHasBaseUrl = !!selectedProviderInfo?.base_url;

  useEffect(() => {
    if (selectedProviderInfo?.base_url) {
      setNewBaseUrl(selectedProviderInfo.base_url);
    } else {
      setNewBaseUrl("");
    }
  }, [newProvider, selectedProviderInfo]);

  useEffect(() => {
    fetchProviders()
      .then(setProviders)
      .catch(() => {});
    listPreconfiguredAgents()
      .then(setPreconfigured)
      .catch(() => {});
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
        tenant_id: "default",
        command: parts,
        llm_provider: newProvider === "custom" ? "" : newProvider,
        model: newModel,
        system_prompt: newSystemPrompt,
        base_url: providerHasBaseUrl ? newBaseUrl : "",
      });
      onLaunch(profile.id);
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : "Failed to create profile",
      );
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="langley-dialog-overlay" data-testid="launch-dialog">
      <div className="langley-dialog">
        <div className="langley-dialog-header">
          <h2>Launch Agent</h2>
          <button
            className="langley-btn"
            onClick={onClose}
            data-testid="close-dialog"
          >
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
                  <span className="langley-preconfigured-provider">
                    {a.provider}
                  </span>
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
                {providerOptions.map((p) => (
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
                  {providerModels.length > 0 && (
                    <datalist id="np-model-suggestions">
                      {providerModels.map((m) => {
                        const cost = formatBilling(m.billing);
                        return (
                          <option key={m.id} value={m.id}>
                            {cost ? `${m.name} — ${cost}` : m.name}
                          </option>
                        );
                      })}
                    </datalist>
                  )}
                  {currentModelBilling && (
                    <span className="langley-model-cost">
                      {formatBilling(currentModelBilling)}
                    </span>
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

              {providerHasBaseUrl && (
                <>
                  <label htmlFor="np-base-url">Base URL</label>
                  <input
                    id="np-base-url"
                    type="text"
                    value={newBaseUrl}
                    onChange={(e) => setNewBaseUrl(e.target.value)}
                    placeholder="http://localhost:1234/v1"
                    data-testid="np-base-url"
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

              {createError && (
                <div className="langley-error">{createError}</div>
              )}
              <div className="langley-actions">
                <button
                  className="langley-btn langley-btn-primary"
                  onClick={handleCreateProfile}
                  disabled={
                    creating || !newName || (!isLLMProvider && !newCommand)
                  }
                  data-testid="create-and-launch"
                >
                  {creating ? "Creating..." : "Create & Launch"}
                </button>
                <button
                  className="langley-btn"
                  onClick={() => setShowNewProfile(false)}
                >
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
