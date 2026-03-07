/**
 * Langley REST API client.
 *
 * All methods return typed data from the langley backend API.
 */

const BASE = "/api";

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
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
  tenant_id: string;
  status: string;
  pid: number | null;
  started_at: number;
  stopped_at: number | null;
  restart_count: number;
  exit_code: number | null;
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
  opts?: { agent_id?: string; restart_policy?: string; environment?: Record<string, string> },
): Promise<AgentInfo> {
  return request<AgentInfo>("/agents", {
    method: "POST",
    body: JSON.stringify({ profile_id: profileId, ...opts }),
  });
}

export async function stopAgent(agentId: string): Promise<{ status: string }> {
  return request(`/agents/${encodeURIComponent(agentId)}/stop`, { method: "POST" });
}

export async function killAgent(agentId: string): Promise<{ status: string }> {
  return request(`/agents/${encodeURIComponent(agentId)}/kill`, { method: "POST" });
}

export async function restartAgent(agentId: string): Promise<AgentInfo> {
  return request<AgentInfo>(`/agents/${encodeURIComponent(agentId)}/restart`, { method: "POST" });
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

export async function listProfiles(
  tenantId?: string,
): Promise<ProfileInfo[]> {
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

export async function deleteProfile(profileId: string): Promise<{ deleted: boolean }> {
  return request(`/profiles/${encodeURIComponent(profileId)}`, {
    method: "DELETE",
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
  const data = await request<{ agents: PreconfiguredAgent[] }>("/agents/preconfigured");
  return data.agents;
}

// Activity feed

export async function fetchActivity(
  limit?: number,
): Promise<AuditEntryInfo[]> {
  const qs = limit ? `?limit=${limit}` : "";
  return request<AuditEntryInfo[]>(`/activity${qs}`);
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

// Health

export async function healthz(): Promise<{ status: string }> {
  return request<{ status: string }>("/healthz");
}

// Providers

export interface ProviderModel {
  id: string;
  name: string;
}

export interface ProviderInfo {
  id: string;
  name: string;
  models: ProviderModel[];
}

export async function fetchProviders(): Promise<ProviderInfo[]> {
  const data = await request<{ providers: ProviderInfo[] }>("/providers");
  return data.providers;
}
