/**
 * Langley REST API client.
 *
 * All methods return typed data from the langley backend API.
 */

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ error: resp.statusText }));
    throw new Error(body.error ?? `HTTP ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

// -- Types matching the backend --

export interface AgentInfo {
  agent_id: string;
  profile_name: string;
  profile_id: string;
  tenant_id: string;
  status: string;
  pid: number | null;
  started_at: number;
  stopped_at: number | null;
  restart_count: number;
  restart_policy: string;
  exit_code: number | null;
  last_heartbeat: number | null;
  uptime_seconds: number;
  error_message: string;
}

export interface TenantInfo {
  id: string;
  name: string;
  created_at: number;
  active: boolean;
  metadata: Record<string, unknown>;
}

export interface ProfileInfo {
  id: string;
  name: string;
  tenant_id: string;
  version: number;
  command: string[];
  llm_provider: string;
  model: string;
  system_prompt: string;
  environment: Record<string, string>;
  tags: string[];
}

export interface MessageInfo {
  id: string;
  channel: string;
  sender: string;
  recipient: string;
  timestamp: number;
  sequence: number;
  body: unknown;
}

export interface AuditEntryInfo {
  id: string;
  tenant_id: string;
  agent_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  timestamp: number;
}

export interface ChannelInfo {
  channel: string;
  message_count: number;
}

export interface CheckpointInfo {
  id: string;
  agent_id: string;
  tenant_id: string;
  sequence: number;
  machine_id: string;
  timestamp: number;
  metadata: Record<string, unknown>;
}

// -- API methods --

export async function listAgents(
  tenantId?: string,
  status?: string,
): Promise<AgentInfo[]> {
  const params = new URLSearchParams();
  if (tenantId) params.set("tenant_id", tenantId);
  if (status) params.set("status", status);
  const qs = params.toString();
  return request<AgentInfo[]>(`/agents${qs ? `?${qs}` : ""}`);
}

export async function getAgent(agentId: string): Promise<AgentInfo> {
  return request<AgentInfo>(`/agents/${encodeURIComponent(agentId)}`);
}

export async function launchAgent(
  profileId: string,
  opts?: {
    agent_id?: string;
    restart_policy?: string;
    environment?: Record<string, string>;
  },
): Promise<AgentInfo> {
  return request<AgentInfo>("/agents", {
    method: "POST",
    body: JSON.stringify({ profile_id: profileId, ...opts }),
  });
}

export async function stopAgent(agentId: string): Promise<{ status: string }> {
  return request(`/agents/${encodeURIComponent(agentId)}/stop`, {
    method: "POST",
  });
}

export async function killAgent(agentId: string): Promise<{ status: string }> {
  return request(`/agents/${encodeURIComponent(agentId)}/kill`, {
    method: "POST",
  });
}

export async function restartAgent(agentId: string): Promise<AgentInfo> {
  return request<AgentInfo>(`/agents/${encodeURIComponent(agentId)}/restart`, {
    method: "POST",
  });
}

export async function sendMessageToAgent(
  agentId: string,
  body: unknown,
): Promise<{ message_id: string; sequence: number }> {
  return request(`/agents/${encodeURIComponent(agentId)}/message`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

// Profiles

export async function listProfiles(tenantId?: string): Promise<ProfileInfo[]> {
  const qs = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
  return request<ProfileInfo[]>(`/profiles${qs}`);
}

export async function createProfile(
  profile: Record<string, unknown>,
): Promise<ProfileInfo> {
  return request<ProfileInfo>("/profiles", {
    method: "POST",
    body: JSON.stringify(profile),
  });
}

export async function getProfile(profileId: string): Promise<ProfileInfo> {
  return request<ProfileInfo>(`/profiles/${encodeURIComponent(profileId)}`);
}

export async function deleteProfile(
  profileId: string,
): Promise<{ deleted: boolean }> {
  return request(`/profiles/${encodeURIComponent(profileId)}`, {
    method: "DELETE",
  });
}

export async function updateProfile(
  profileId: string,
  updates: Partial<
    Pick<
      ProfileInfo,
      | "name"
      | "llm_provider"
      | "model"
      | "system_prompt"
      | "command"
      | "environment"
      | "tags"
    >
  >,
): Promise<ProfileInfo> {
  return request<ProfileInfo>(`/profiles/${encodeURIComponent(profileId)}`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
}

// Preconfigured agents

export interface PreconfiguredAgent {
  name: string;
  provider: string;
  model: string;
  system_prompt: string;
  source: string;
}

export async function listPreconfiguredAgents(): Promise<PreconfiguredAgent[]> {
  const data = await request<{ agents: PreconfiguredAgent[] }>(
    "/agents/preconfigured",
  );
  return data.agents;
}

export async function saveAgentToDisk(profile: {
  name: string;
  provider: string;
  model?: string;
  system_prompt?: string;
  path?: string;
}): Promise<{ path: string }> {
  return request<{ path: string }>("/agents/preconfigured/save", {
    method: "POST",
    body: JSON.stringify(profile),
  });
}

export async function generateAgentProfile(
  agentId: string,
): Promise<{ message_id: string; sequence: number; prompt_sent: string }> {
  return request(`/agents/${encodeURIComponent(agentId)}/generate-profile`, {
    method: "POST",
  });
}

// Activity feed

export async function fetchActivity(limit?: number): Promise<AuditEntryInfo[]> {
  const qs = limit ? `?limit=${limit}` : "";
  return request<AuditEntryInfo[]>(`/activity${qs}`);
}

export async function queryAudit(
  tenantId: string,
  opts?: {
    agent_id?: string;
    event_type?: string;
    limit?: number;
    offset?: number;
  },
): Promise<AuditEntryInfo[]> {
  const params = new URLSearchParams({ tenant_id: tenantId });
  if (opts?.agent_id) params.set("agent_id", opts.agent_id);
  if (opts?.event_type) params.set("event_type", opts.event_type);
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  return request<AuditEntryInfo[]>(`/audit?${params}`);
}

// Tenants

export async function listTenants(): Promise<TenantInfo[]> {
  return request<TenantInfo[]>("/tenants");
}

// Messages

export async function queryMessages(
  channel: string,
  opts?: { from_seq?: number; limit?: number },
): Promise<MessageInfo[]> {
  const params = new URLSearchParams({ channel });
  if (opts?.from_seq) params.set("from_seq", String(opts.from_seq));
  if (opts?.limit) params.set("limit", String(opts.limit));
  return request<MessageInfo[]>(`/messages?${params}`);
}

// Channels

export async function listChannels(): Promise<ChannelInfo[]> {
  return request<ChannelInfo[]>("/channels");
}

// Checkpoints

export async function listCheckpoints(
  agentId: string,
): Promise<CheckpointInfo[]> {
  return request<CheckpointInfo[]>(
    `/agents/${encodeURIComponent(agentId)}/checkpoints`,
  );
}

// Message replay

export async function replayMessage(
  sourceChannel: string,
  messageId: string,
  targetChannel: string,
): Promise<{ message_id: string; sequence: number }> {
  return request(`/messages/replay`, {
    method: "POST",
    body: JSON.stringify({
      source_channel: sourceChannel,
      message_id: messageId,
      target_channel: targetChannel,
    }),
  });
}

// Health

export async function healthz(): Promise<{ status: string }> {
  return request<{ status: string }>("/healthz");
}

// Providers

export interface ModelBilling {
  type: "multiplier" | "per_token";
  multiplier?: number;
  input_per_mtok?: number;
  output_per_mtok?: number;
}

export interface ProviderModel {
  id: string;
  name: string;
  billing?: ModelBilling;
}

export interface ProviderInfo {
  id: string;
  name: string;
  models: ProviderModel[];
  /** Endpoint URL (only for OpenAI-compatible providers like LM Studio). */
  base_url?: string;
  /** Whether the discovery probe succeeded. */
  online?: boolean;
}

export async function fetchProviders(): Promise<ProviderInfo[]> {
  const data = await request<{ providers: ProviderInfo[] }>("/providers");
  return data.providers;
}
