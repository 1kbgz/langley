"""Langley REST API — Starlette routes for the control plane.

Provides CRUD endpoints for tenants, agents, profiles, messages, and audit.
"""

import json
import logging
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from langley.discovery import discover_agents, save_agent_to_disk
from langley.models import AgentProfile, Message
from langley.server_state import ServerState
from langley.supervisor import AgentStatus, RestartPolicy
from langley.websocket import websocket_endpoint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status)


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    return json.loads(raw)


def _state(request: Request) -> ServerState:
    return request.app.state.server


# ---------------------------------------------------------------------------
# Tenant endpoints
# ---------------------------------------------------------------------------


async def create_tenant(request: Request) -> Response:
    data = await _body(request)
    name = data.get("name", "")
    if not name:
        return _error("name is required")
    state = _state(request)
    try:
        tenant = state.tenant_manager.create_tenant(
            name=name,
            metadata=data.get("metadata"),
            resource_quotas=data.get("resource_quotas"),
        )
    except ValueError as e:
        return _error(str(e), 409)
    return _json(tenant.to_dict(), 201)


async def get_tenant(request: Request) -> Response:
    tenant_id = request.path_params["tenant_id"]
    state = _state(request)
    tenant = state.tenant_manager.get_tenant(tenant_id)
    if tenant is None:
        return _error("Tenant not found", 404)
    return _json(tenant.to_dict())


async def list_tenants(request: Request) -> Response:
    state = _state(request)
    include_inactive = request.query_params.get("include_inactive", "false").lower() == "true"
    tenants = state.tenant_manager.list_tenants(active_only=not include_inactive)
    return _json([t.to_dict() for t in tenants])


# ---------------------------------------------------------------------------
# Agent endpoints
# ---------------------------------------------------------------------------


async def launch_agent(request: Request) -> Response:
    data = await _body(request)
    profile_id = data.get("profile_id", "")
    state = _state(request)

    if profile_id:
        profile = state.profile_store.get(profile_id)
        if profile is None:
            return _error("Profile not found", 404)
    else:
        # Inline profile
        try:
            profile = AgentProfile.from_dict(data.get("profile", {}))
        except (TypeError, KeyError) as e:
            return _error(f"Invalid profile: {e}")

    if not profile.name:
        return _error("Profile must have a name")

    restart_str = data.get("restart_policy", "never")
    try:
        restart_policy = RestartPolicy(restart_str)
    except ValueError:
        return _error(f"Invalid restart_policy: {restart_str}")

    try:
        info = state.supervisor.launch(
            profile=profile,
            agent_id=data.get("agent_id"),
            restart_policy=restart_policy,
            environment=data.get("environment"),
        )
    except ValueError as e:
        return _error(str(e), 409)
    except RuntimeError as e:
        return _error(str(e), 503)

    return _json(info.to_dict(), 201)


async def list_agents(request: Request) -> Response:
    state = _state(request)
    tenant_id = request.query_params.get("tenant_id")
    status_filter = request.query_params.get("status")

    agents = state.supervisor.list_agents(tenant_id=tenant_id)
    if status_filter:
        agents = [a for a in agents if a.status.value == status_filter]

    return _json([a.to_dict() for a in agents])


async def get_agent(request: Request) -> Response:
    agent_id = request.path_params["agent_id"]
    state = _state(request)
    info = state.supervisor.get_agent(agent_id)
    if info is None:
        return _error("Agent not found", 404)
    return _json(info.to_dict())


async def stop_agent(request: Request) -> Response:
    agent_id = request.path_params["agent_id"]
    state = _state(request)
    ok = state.supervisor.stop(agent_id)
    if not ok:
        return _error("Agent not found or not running", 404)
    return _json({"status": "stopping"})


async def kill_agent(request: Request) -> Response:
    agent_id = request.path_params["agent_id"]
    state = _state(request)
    ok = state.supervisor.stop(agent_id, force=True)
    if not ok:
        return _error("Agent not found or not running", 404)
    return _json({"status": "killed"})


async def restart_agent(request: Request) -> Response:
    agent_id = request.path_params["agent_id"]
    state = _state(request)
    info = state.supervisor.restart(agent_id)
    if info is None:
        return _error("Agent not found", 404)
    return _json(info.to_dict())


async def send_message_to_agent(request: Request) -> Response:
    agent_id = request.path_params["agent_id"]
    state = _state(request)
    data = await _body(request)
    body = data.get("body", {})
    channel = f"agent.{agent_id}.inbox"
    msg = Message(
        channel=channel,
        body=body,
        sender="api",
        recipient=agent_id,
        headers=data.get("headers", {}),
    )
    receipt = state.transport.send(channel, msg)
    return _json({"message_id": receipt.message_id, "sequence": receipt.sequence}, 201)


# ---------------------------------------------------------------------------
# Profile endpoints
# ---------------------------------------------------------------------------


async def list_profiles(request: Request) -> Response:
    state = _state(request)
    tenant_id = request.query_params.get("tenant_id")
    profiles = state.profile_store.list_profiles(tenant_id=tenant_id)
    return _json([p.to_dict() for p in profiles])


async def create_profile(request: Request) -> Response:
    state = _state(request)
    data = await _body(request)
    try:
        profile = AgentProfile.from_dict(data)
    except (TypeError, KeyError) as e:
        return _error(f"Invalid profile: {e}")
    if not profile.name:
        return _error("Profile must have a name")
    saved = state.profile_store.save(profile)
    return _json(saved.to_dict(), 201)


async def get_profile(request: Request) -> Response:
    profile_id = request.path_params["profile_id"]
    state = _state(request)
    version = request.query_params.get("version")
    ver = int(version) if version else None
    profile = state.profile_store.get(profile_id, version=ver)
    if profile is None:
        return _error("Profile not found", 404)
    return _json(profile.to_dict())


async def delete_profile(request: Request) -> Response:
    profile_id = request.path_params["profile_id"]
    state = _state(request)
    ok = state.profile_store.delete(profile_id)
    if not ok:
        return _error("Profile not found", 404)
    return _json({"deleted": True})


async def update_profile(request: Request) -> Response:
    profile_id = request.path_params["profile_id"]
    state = _state(request)
    existing = state.profile_store.get(profile_id)
    if existing is None:
        return _error("Profile not found", 404)
    data = await _body(request)
    # Apply updates to existing profile fields
    for field in ("name", "llm_provider", "model", "system_prompt", "command", "environment", "tags", "tenant_id"):
        if field in data:
            setattr(existing, field, data[field])
    saved = state.profile_store.save(existing)
    return _json(saved.to_dict())


# ---------------------------------------------------------------------------
# Message endpoints
# ---------------------------------------------------------------------------


async def query_messages(request: Request) -> Response:
    state = _state(request)
    channel = request.query_params.get("channel", "")
    if not channel:
        return _error("channel query parameter is required")
    from_seq = int(request.query_params.get("from_seq", "0"))
    limit = int(request.query_params.get("limit", "100"))
    msgs = []
    for msg in state.router.replay(channel, from_seq=from_seq):
        msgs.append(msg.to_dict())
        if len(msgs) >= limit:
            break
    return _json(msgs)


# ---------------------------------------------------------------------------
# Audit endpoints
# ---------------------------------------------------------------------------


async def query_audit(request: Request) -> Response:
    state = _state(request)
    tenant_id = request.query_params.get("tenant_id", "")
    if not tenant_id:
        return _error("tenant_id query parameter is required")
    agent_id = request.query_params.get("agent_id")
    event_type = request.query_params.get("event_type")
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))

    entries = state.audit_log.query(
        tenant_id=tenant_id,
        agent_id=agent_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return _json([e.to_dict() for e in entries])


async def activity_feed(request: Request) -> Response:
    """Return recent audit events across all tenants (for the activity feed)."""
    state = _state(request)
    limit = int(request.query_params.get("limit", "50"))
    entries = state.audit_log.recent(limit=limit)
    return _json([e.to_dict() for e in entries])


async def list_channels(request: Request) -> Response:
    """Return all known message channels."""
    state = _state(request)
    channels: list[str] = []
    if hasattr(state.transport, "list_channels"):
        channels = state.transport.list_channels()
    result = []
    for ch in channels:
        # Count messages by replaying (cheap for file transport)
        count = sum(1 for _ in state.router.replay(ch, from_seq=0))
        result.append({"channel": ch, "message_count": count})
    return _json(result)


async def list_agent_checkpoints(request: Request) -> Response:
    """Return checkpoints for an agent (metadata only, no state blob)."""
    agent_id = request.path_params["agent_id"]
    state = _state(request)
    checkpoints = state.state_store.list_checkpoints(agent_id)
    return _json(
        [
            {
                "id": cp.id,
                "agent_id": cp.agent_id,
                "tenant_id": cp.tenant_id,
                "sequence": cp.sequence,
                "machine_id": cp.machine_id,
                "timestamp": cp.timestamp,
                "metadata": cp.metadata,
            }
            for cp in checkpoints
        ]
    )


async def replay_message(request: Request) -> Response:
    """Re-send a historical message to a target channel."""
    data = await _body(request)
    source_channel = data.get("source_channel", "")
    message_id = data.get("message_id", "")
    target_channel = data.get("target_channel", "")
    if not source_channel or not message_id or not target_channel:
        return _error("source_channel, message_id, and target_channel are required")
    state = _state(request)
    for msg in state.router.replay(source_channel, from_seq=0):
        if msg.id == message_id:
            replayed = Message(
                channel=target_channel,
                body=msg.body,
                sender=msg.sender,
                recipient=msg.recipient,
                headers={**msg.headers, "replayed_from": message_id},
                correlation_id=msg.correlation_id,
            )
            receipt = state.transport.send(target_channel, replayed)
            return _json({"message_id": receipt.message_id, "sequence": receipt.sequence}, 201)
    return _error("Message not found", 404)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def _copilot_billing(multiplier: float) -> dict[str, Any]:
    """Build a billing dict for a Copilot model."""
    return {"type": "multiplier", "multiplier": multiplier}


def _token_billing(input_per_mtok: float, output_per_mtok: float) -> dict[str, Any]:
    """Build a billing dict for a per-token provider."""
    return {
        "type": "per_token",
        "input_per_mtok": input_per_mtok,
        "output_per_mtok": output_per_mtok,
    }


# Static fallback for GitHub Copilot when the SDK is unavailable.
# Multipliers sourced from https://docs.github.com/en/copilot/concepts/billing/copilot-requests#model-multipliers
_COPILOT_FALLBACK_MODELS = [
    {"id": "claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "billing": _copilot_billing(1.0)},
    {"id": "claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "billing": _copilot_billing(1.0)},
    {"id": "claude-haiku-4.5", "name": "Claude Haiku 4.5", "billing": _copilot_billing(0.33)},
    {"id": "claude-opus-4.6", "name": "Claude Opus 4.6", "billing": _copilot_billing(3.0)},
    {"id": "claude-opus-4.5", "name": "Claude Opus 4.5", "billing": _copilot_billing(3.0)},
    {"id": "claude-sonnet-4", "name": "Claude Sonnet 4", "billing": _copilot_billing(1.0)},
    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "billing": _copilot_billing(1.0)},
    {"id": "gemini-3-pro-preview", "name": "Gemini 3 Pro Preview", "billing": _copilot_billing(1.0)},
    {"id": "gpt-5.4", "name": "GPT-5.4", "billing": _copilot_billing(1.0)},
    {"id": "gpt-5.2", "name": "GPT-5.2", "billing": _copilot_billing(1.0)},
    {"id": "gpt-5.1", "name": "GPT-5.1", "billing": _copilot_billing(1.0)},
    {"id": "gpt-5.1-codex", "name": "GPT-5.1 Codex", "billing": _copilot_billing(1.0)},
    {"id": "gpt-5.1-codex-mini", "name": "GPT-5.1 Codex Mini", "billing": _copilot_billing(0.33)},
    {"id": "gpt-5-mini", "name": "GPT-5 mini", "billing": _copilot_billing(0.0)},
    {"id": "gpt-4.1", "name": "GPT-4.1", "billing": _copilot_billing(0.0)},
]


async def list_providers(request: Request) -> Response:
    """Return available LLM providers and their models.

    Attempts to query the copilot CLI for live model data; falls back to a
    static list when the CLI is unavailable.  Each model includes billing
    information so the UI can display costs.
    """
    providers: list[dict[str, Any]] = []

    # Try to get live model list from copilot CLI
    try:
        from copilot import CopilotClient

        client = CopilotClient()
        await client.start()
        try:
            models = await client.list_models()
            copilot_models = []
            for m in models:
                multiplier = 1.0
                if m.billing:
                    multiplier = getattr(m.billing, "multiplier", 1.0)
                copilot_models.append(
                    {
                        "id": m.id,
                        "name": getattr(m, "name", m.id),
                        "billing": _copilot_billing(multiplier),
                    }
                )
            if copilot_models:
                providers.append(
                    {
                        "id": "github-copilot",
                        "name": "GitHub Copilot",
                        "models": copilot_models,
                    }
                )
        finally:
            await client.stop()
    except Exception:
        # Copilot CLI not available — use static fallback
        providers.append(
            {
                "id": "github-copilot",
                "name": "GitHub Copilot",
                "models": list(_COPILOT_FALLBACK_MODELS),
            }
        )

    # Static entries for other providers (no live discovery yet).
    # Pricing sourced from provider websites as of March 2026.
    providers.extend(
        [
            {
                "id": "openai",
                "name": "OpenAI",
                "models": [
                    {"id": "gpt-5.4", "name": "GPT-5.4", "billing": _token_billing(2.50, 15.00)},
                    {"id": "gpt-5-mini", "name": "GPT-5 mini", "billing": _token_billing(0.25, 2.00)},
                    {"id": "gpt-4.1", "name": "GPT-4.1", "billing": _token_billing(2.00, 8.00)},
                    {"id": "gpt-4.1-mini", "name": "GPT-4.1 mini", "billing": _token_billing(0.40, 1.60)},
                    {"id": "gpt-4.1-nano", "name": "GPT-4.1 nano", "billing": _token_billing(0.10, 0.40)},
                    {"id": "o4-mini", "name": "o4-mini", "billing": _token_billing(1.10, 4.40)},
                ],
            },
            {
                "id": "anthropic",
                "name": "Anthropic",
                "models": [
                    {"id": "claude-opus-4-6", "name": "Claude Opus 4.6", "billing": _token_billing(5.00, 25.00)},
                    {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "billing": _token_billing(3.00, 15.00)},
                    {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5", "billing": _token_billing(1.00, 5.00)},
                ],
            },
            {
                "id": "google",
                "name": "Google",
                "models": [
                    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "billing": _token_billing(1.25, 10.00)},
                    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "billing": _token_billing(0.30, 2.50)},
                    {"id": "gemini-3-pro-preview", "name": "Gemini 3 Pro Preview", "billing": _token_billing(2.00, 12.00)},
                    {"id": "gemini-3-flash-preview", "name": "Gemini 3 Flash Preview", "billing": _token_billing(0.50, 3.00)},
                ],
            },
        ]
    )

    return _json({"providers": providers})


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def list_preconfigured_agents(request: Request) -> Response:
    """Return agent profiles discovered from well-known config directories."""
    agents = discover_agents()
    return _json({"agents": [a.to_dict() for a in agents]})


async def save_agent_to_disk_endpoint(request: Request) -> Response:
    """Save a profile to disk as markdown with YAML frontmatter.

    Accepts JSON body with: name, provider, model, system_prompt, path (optional).
    If path is omitted the file goes to the provider's default agents directory.
    """
    data = await _body(request)
    name = data.get("name", "")
    if not name:
        return _error("name is required")
    provider = data.get("provider", "")
    model = data.get("model", "")
    system_prompt = data.get("system_prompt", "")
    path = data.get("path")  # optional explicit path

    try:
        written = save_agent_to_disk(
            name=name,
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            path=path,
        )
    except ValueError as e:
        return _error(str(e))

    return _json({"path": written}, 201)


async def generate_agent_profile(request: Request) -> Response:
    """Send a running agent a pre-canned prompt to generate a self-profile.

    The agent is asked to describe itself as a markdown agentic profile.
    Returns the generated profile text.
    """
    agent_id = request.path_params["agent_id"]
    state = _state(request)
    info = state.supervisor.get_agent(agent_id)
    if info is None:
        return _error("Agent not found", 404)
    if info.status != AgentStatus.RUNNING:
        return _error("Agent is not running", 409)

    prompt = (
        "Please generate a concise agentic profile for yourself in Markdown format. "
        "Include YAML frontmatter with `name`, `provider`, and `model` fields. "
        "After the frontmatter, write a brief description of your capabilities, "
        "specialties, and the kind of tasks you are best suited for. "
        "Keep it under 500 words. Output ONLY the markdown — no wrapping code fences."
    )

    channel = f"agent.{agent_id}.inbox"
    msg = Message(
        channel=channel,
        body=prompt,
        sender="api",
        recipient=agent_id,
        headers={"type": "generate_profile"},
    )
    receipt = state.transport.send(channel, msg)
    return _json(
        {
            "message_id": receipt.message_id,
            "sequence": receipt.sequence,
            "prompt_sent": prompt,
        }
    )


async def healthz(request: Request) -> Response:
    return _json({"status": "ok"})


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_api_routes() -> list[Route]:
    """Return the list of API routes."""
    return [
        # Health
        Route("/api/healthz", healthz, methods=["GET"]),
        # Providers
        Route("/api/providers", list_providers, methods=["GET"]),
        # Preconfigured Agents
        Route("/api/agents/preconfigured", list_preconfigured_agents, methods=["GET"]),
        Route("/api/agents/preconfigured/save", save_agent_to_disk_endpoint, methods=["POST"]),
        # Tenants
        Route("/api/tenants", create_tenant, methods=["POST"]),
        Route("/api/tenants", list_tenants, methods=["GET"]),
        Route("/api/tenants/{tenant_id}", get_tenant, methods=["GET"]),
        # Agents
        Route("/api/agents", launch_agent, methods=["POST"]),
        Route("/api/agents", list_agents, methods=["GET"]),
        Route("/api/agents/{agent_id}", get_agent, methods=["GET"]),
        Route("/api/agents/{agent_id}/stop", stop_agent, methods=["POST"]),
        Route("/api/agents/{agent_id}/kill", kill_agent, methods=["POST"]),
        Route("/api/agents/{agent_id}/restart", restart_agent, methods=["POST"]),
        Route("/api/agents/{agent_id}/message", send_message_to_agent, methods=["POST"]),
        Route("/api/agents/{agent_id}/generate-profile", generate_agent_profile, methods=["POST"]),
        # Profiles
        Route("/api/profiles", list_profiles, methods=["GET"]),
        Route("/api/profiles", create_profile, methods=["POST"]),
        Route("/api/profiles/{profile_id}", get_profile, methods=["GET"]),
        Route("/api/profiles/{profile_id}", update_profile, methods=["PUT"]),
        Route("/api/profiles/{profile_id}", delete_profile, methods=["DELETE"]),
        # Messages
        Route("/api/messages", query_messages, methods=["GET"]),
        Route("/api/messages/replay", replay_message, methods=["POST"]),
        # Channels
        Route("/api/channels", list_channels, methods=["GET"]),
        # Checkpoints
        Route("/api/agents/{agent_id}/checkpoints", list_agent_checkpoints, methods=["GET"]),
        # Audit / Activity
        Route("/api/audit", query_audit, methods=["GET"]),
        Route("/api/activity", activity_feed, methods=["GET"]),
        # WebSocket
        WebSocketRoute("/ws", websocket_endpoint),
    ]


def create_app(server_state: ServerState | None = None) -> Starlette:
    """Create the Starlette ASGI application."""
    if server_state is None:
        server_state = ServerState.create_default()

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ]

    routes = create_api_routes()

    # Mount static files if available
    if server_state.static_dir and server_state.static_dir.is_dir():
        routes.append(Mount("/", app=StaticFiles(directory=str(server_state.static_dir), html=True), name="static"))

    app = Starlette(routes=routes, middleware=middleware)
    app.state.server = server_state

    return app
