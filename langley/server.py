"""Langley REST API — Starlette routes for the control plane.

Provides CRUD endpoints for tenants, agents, profiles, messages, and audit.
"""

import json
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket

from langley.models import AgentProfile, AuditEntry, Message
from langley.server_state import ServerState
from langley.supervisor import AgentStatus, RestartPolicy
from langley.websocket import websocket_endpoint


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


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

async def list_providers(request: Request) -> Response:
    """Return available LLM providers and their models.

    Attempts to query the copilot CLI for live model data; falls back to a
    static list when the CLI is unavailable.
    """
    providers: list[dict[str, Any]] = []

    # Try to get live model list from copilot CLI
    try:
        from copilot import CopilotClient

        client = CopilotClient()
        await client.start()
        try:
            models = await client.list_models()
            copilot_models = [
                {"id": m.id, "name": getattr(m, "name", m.id)}
                for m in models
            ]
            if copilot_models:
                providers.append({
                    "id": "github-copilot",
                    "name": "GitHub Copilot",
                    "models": copilot_models,
                })
        finally:
            await client.stop()
    except Exception:
        # Copilot CLI not available — use static fallback
        providers.append({
            "id": "github-copilot",
            "name": "GitHub Copilot",
            "models": [
                {"id": "claude-sonnet-4", "name": "claude-sonnet-4"},
                {"id": "gpt-4o", "name": "gpt-4o"},
                {"id": "o4-mini", "name": "o4-mini"},
            ],
        })

    # Static entries for other providers (no live discovery yet)
    providers.extend([
        {
            "id": "openai",
            "name": "OpenAI",
            "models": [
                {"id": "gpt-4o", "name": "gpt-4o"},
                {"id": "gpt-4.1", "name": "gpt-4.1"},
                {"id": "o4-mini", "name": "o4-mini"},
            ],
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "models": [
                {"id": "claude-sonnet-4", "name": "claude-sonnet-4"},
                {"id": "claude-opus-4", "name": "claude-opus-4"},
            ],
        },
        {
            "id": "google",
            "name": "Google",
            "models": [
                {"id": "gemini-2.5-pro", "name": "gemini-2.5-pro"},
                {"id": "gemini-2.5-flash", "name": "gemini-2.5-flash"},
            ],
        },
    ])

    return _json({"providers": providers})


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

async def list_preconfigured_agents(request: Request) -> Response:
    """Return agent profiles discovered from well-known config directories."""
    from langley.discovery import discover_agents

    agents = discover_agents()
    return _json({"agents": [a.to_dict() for a in agents]})


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
        # Profiles
        Route("/api/profiles", list_profiles, methods=["GET"]),
        Route("/api/profiles", create_profile, methods=["POST"]),
        Route("/api/profiles/{profile_id}", get_profile, methods=["GET"]),
        Route("/api/profiles/{profile_id}", delete_profile, methods=["DELETE"]),
        # Messages
        Route("/api/messages", query_messages, methods=["GET"]),
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
        routes.append(
            Mount("/", app=StaticFiles(directory=str(server_state.static_dir), html=True), name="static")
        )

    app = Starlette(routes=routes, middleware=middleware)
    app.state.server = server_state

    return app
